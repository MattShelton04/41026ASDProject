"""Build the cloud deployment report from a deployment's own outputs (Release 2, R2-45).

``cloud-deployment.yml`` runs this after every Azure deployment, and an operator can run it after
``deploy.sh`` on a laptop. It reads only files the deployment wrote into its log directory:

    outputs.txt                Bicep outputs (deploy.sh provision / outputs)
    image-tag.txt              the pushed image tag (the commit SHA)
    vm-deploy.log              the VM's run-command output, ending in PROPERTYSCOPE_RESULT=...
    smoke/cloud-smoke.json     scripts/cloud_smoke.py results
    endpoint-security.txt      deployment/azure/validate-endpoint-security.sh (optional)
    data-security.txt          deployment/azure/validate-data-security.sh (optional)

Stage outcomes come from ``--stage name=outcome`` (the workflow passes ``steps.<id>.outcome``)
and the run's identity from the standard GitHub Actions environment variables. The Markdown
follows docs/release-2/evidence/cloud/README.md; a JSON twin is written next to it for the
agentic-loop Cloud Deployment Review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = REPOSITORY_ROOT / ".propertyscope-runtime" / "cloud"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "release-2" / "evidence" / "cloud"
STAGE_ORDER = ("provision", "push", "deploy", "smoke", "endpoint_security", "data_security")
STAGE_LABELS = {
    "provision": "Provision (resource group + Bicep)",
    "push": "Build and push images to ACR",
    "deploy": "Deploy to the VM (az vm run-command)",
    "smoke": "Public smoke test",
    "endpoint_security": "Endpoint security validation (B5)",
    "data_security": "Data security validation (B6)",
}
REQUIRED_STAGES = ("push", "deploy", "smoke")
# Provisioning may be skipped on a manual redeploy of existing infrastructure.
OPTIONAL_REQUIRED_STAGES = ("provision",)
RESULT_LINE = re.compile(r"^PROPERTYSCOPE_RESULT=(\{.*\})\s*$", re.MULTILINE)
VALIDATION_LINE = re.compile(r"^(PASS|FAIL|SKIP|INFO) (.+)$", re.MULTILINE)


@dataclass(slots=True)
class DeploymentEvidence:
    """Everything the report states, gathered from files and the run environment."""

    generated_at: str
    run: dict[str, str]
    stages: dict[str, str]
    outputs: dict[str, str] = field(default_factory=dict)
    image_tag: str | None = None
    vm_result: dict[str, Any] | None = None
    smoke: dict[str, Any] | None = None
    endpoint_security: list[tuple[str, str]] = field(default_factory=list)
    data_security: list[tuple[str, str]] = field(default_factory=list)
    evidence_files: list[str] = field(default_factory=list)

    @property
    def smoke_passed(self) -> bool:
        return bool(self.smoke and self.smoke.get("passed"))

    @property
    def verdict(self) -> str:
        required = all(self.stages.get(stage) == "success" for stage in REQUIRED_STAGES) and all(
            self.stages.get(stage, "skipped") in {"success", "skipped"}
            for stage in OPTIONAL_REQUIRED_STAGES
        )
        return "SUCCEEDED" if required and self.smoke_passed else "FAILED"

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "verdict": self.verdict,
            "run": self.run,
            "stages": self.stages,
            "outputs": self.outputs,
            "image_tag": self.image_tag,
            "vm_result": self.vm_result,
            "smoke_summary": (self.smoke or {}).get("summary"),
            "smoke_passed": self.smoke_passed,
            "ai_tier": ai_tier_state(self),
            "endpoint_security": [list(item) for item in self.endpoint_security],
            "data_security": [list(item) for item in self.data_security],
            "evidence_files": self.evidence_files,
        }


def parse_outputs(text: str) -> dict[str, str]:
    """Read ``key=value`` lines (deploy.sh outputs)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and re.fullmatch(r"[a-z_]+", key):
            values[key] = value.strip()
    return values


def parse_vm_result(text: str) -> dict[str, Any] | None:
    """Return the last PROPERTYSCOPE_RESULT JSON the VM printed, if any."""
    matches = RESULT_LINE.findall(text)
    for candidate in reversed(matches):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_validation(text: str) -> list[tuple[str, str]]:
    return [(verdict, detail.strip()) for verdict, detail in VALIDATION_LINE.findall(text)]


def parse_stages(values: Sequence[str]) -> dict[str, str]:
    stages: dict[str, str] = {}
    for value in values:
        name, separator, outcome = value.partition("=")
        if not separator or name not in STAGE_LABELS:
            raise ValueError(f"--stage must be one of {', '.join(STAGE_ORDER)} as name=outcome")
        stages[name] = outcome or "skipped"
    return stages


def run_identity(environment: Mapping[str, str]) -> dict[str, str]:
    server = environment.get("GITHUB_SERVER_URL", "https://github.com")
    repository = environment.get("GITHUB_REPOSITORY", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    identity = {
        "repository": repository,
        "workflow": environment.get("GITHUB_WORKFLOW", "local deploy.sh"),
        "event": environment.get("GITHUB_EVENT_NAME", "local"),
        "actor": environment.get("GITHUB_ACTOR", environment.get("USER", "operator")),
        "commit": environment.get("PROPERTYSCOPE_DEPLOY_SHA", environment.get("GITHUB_SHA", "")),
        "run_attempt": environment.get("GITHUB_RUN_ATTEMPT", ""),
        "run_url": f"{server}/{repository}/actions/runs/{run_id}" if repository and run_id else "",
        "ci_run_url": environment.get("PROPERTYSCOPE_CI_RUN_URL", ""),
    }
    return {key: value for key, value in identity.items() if value}


def collect(
    log_dir: Path, *, stages: Mapping[str, str], environment: Mapping[str, str]
) -> DeploymentEvidence:
    def read(name: str) -> str | None:
        path = log_dir / name
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None

    evidence = DeploymentEvidence(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        run=run_identity(environment),
        stages=dict(stages),
    )
    if (text := read("outputs.txt")) is not None:
        evidence.outputs = parse_outputs(text)
    if (text := read("image-tag.txt")) is not None:
        evidence.image_tag = text.strip() or None
    if (text := read("vm-deploy.log")) is not None:
        evidence.vm_result = parse_vm_result(text)
    if (text := read("smoke/cloud-smoke.json")) is not None:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        evidence.smoke = value if isinstance(value, dict) else None
    if (text := read("endpoint-security.txt")) is not None:
        evidence.endpoint_security = parse_validation(text)
    if (text := read("data-security.txt")) is not None:
        evidence.data_security = parse_validation(text)
    evidence.evidence_files = sorted(
        path.relative_to(log_dir).as_posix()
        for path in log_dir.rglob("*")
        if path.is_file() and not path.name.endswith(".payload.sh")
    )
    if evidence.image_tag is None and evidence.vm_result is not None:
        tag = evidence.vm_result.get("image_tag")
        evidence.image_tag = str(tag) if tag else None
    return evidence


def ai_tier_state(evidence: DeploymentEvidence) -> str:
    """Describe the AI tier from the VM's own report and the smoke test's AI check."""
    vm = (evidence.vm_result or {}).get("cloud_ai")
    check = next(
        (item for item in (evidence.smoke or {}).get("checks", []) if item.get("category") == "ai"),
        None,
    )
    observed = str(check.get("detail", "")).split(":", 1)[0] if check else "not checked"
    flag = {"true": "on", "false": "off"}.get(str(vm), "unknown")
    return f"flag {flag} (PROPERTYSCOPE_CLOUD_AI), edge reports {observed}"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render(evidence: DeploymentEvidence) -> str:
    run, outputs = evidence.run, evidence.outputs
    url = outputs.get("public_url") or (
        f"https://{outputs['fqdn']}" if outputs.get("fqdn") else "not recorded"
    )
    lines = [
        "# Cloud deployment report",
        "",
        f"Generated {evidence.generated_at} by `scripts/cloud_deployment_report.py` from the "
        "deployment's own logs.",
        "",
        "## Summary",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Result | **{evidence.verdict}** |",
        f"| Public URL | {url} |",
        f"| Commit / image tag | `{run.get('commit') or evidence.image_tag or 'unknown'}` / "
        f"`{evidence.image_tag or 'unknown'}` |",
        f"| Trigger | {run.get('event', 'local')} by {run.get('actor', 'operator')} |",
        f"| Workflow run | {run.get('run_url') or 'local run (no GitHub Actions run)'} |",
        f"| Gating CI run | {run.get('ci_run_url') or 'n/a (manual dispatch or local run)'} |",
        f"| AI tier | {ai_tier_state(evidence)} |",
        "",
        "## Pipeline stages",
        "",
        "| Stage | Outcome |",
        "|---|---|",
    ]
    for stage in STAGE_ORDER:
        outcome = evidence.stages.get(stage, "not run")
        lines.append(f"| {STAGE_LABELS[stage]} | {outcome} |")
    lines += ["", "## Azure resources", ""]
    if outputs:
        lines += ["| Output | Value |", "|---|---|"]
        lines += [f"| {key} | `{_cell(value)}` |" for key, value in sorted(outputs.items())]
    else:
        lines.append("No Bicep outputs were recorded.")
    lines += ["", "## VM deployment", ""]
    if evidence.vm_result:
        vm = evidence.vm_result
        lines += [
            f"- Containers running: {vm.get('containers_running', '?')} of "
            f"{vm.get('containers_total', '?')}",
            f"- Image tag on the VM: `{vm.get('image_tag', 'unknown')}`",
            f"- Cloud AI flag: {vm.get('cloud_ai', 'unknown')}",
            "- Host AI units: "
            + ", ".join(f"{name} {state}" for name, state in (vm.get("ai_units") or {}).items()),
        ]
    else:
        lines.append("The VM did not report a deployment result (see vm-deploy.log).")
    lines += ["", "## Public smoke test", ""]
    if evidence.smoke:
        summary = evidence.smoke.get("summary", {})
        lines += [
            f"Target `{evidence.smoke.get('base_url')}`: {summary.get('passed', 0)} of "
            f"{summary.get('total', 0)} checks passed.",
            "",
            "| Owner | Passed | Failed |",
            "|---|---|---|",
        ]
        for owner, counts in sorted(summary.get("by_owner", {}).items()):
            lines.append(f"| {owner} | {counts.get('passed', 0)} | {counts.get('failed', 0)} |")
        lines += ["", "| Result | Owner | Check | Detail |", "|---|---|---|---|"]
        for check in evidence.smoke.get("checks", []):
            verdict = "PASS" if check.get("passed") else "FAIL"
            lines.append(
                f"| {verdict} | {check.get('owner')} | {_cell(check.get('name'))} "
                f"| {_cell(check.get('detail'))} |"
            )
    else:
        lines.append("No smoke-test results were recorded.")
    for title, results in (
        ("Endpoint security validation (bonus B5)", evidence.endpoint_security),
        ("Data security validation (bonus B6)", evidence.data_security),
    ):
        if not results:
            continue
        failed = sum(verdict == "FAIL" for verdict, _ in results)
        lines += [
            "",
            f"## {title}",
            "",
            f"{len(results) - failed} of {len(results)} lines without failure.",
            "",
            "| Result | Check |",
            "|---|---|",
        ]
        lines += [f"| {verdict} | {_cell(detail)} |" for verdict, detail in results]
    lines += [
        "",
        "## Evidence files",
        "",
        *(f"- `{name}`" for name in evidence.evidence_files),
        "",
        "## Review and release decision",
        "",
        "This report is input to the agentic-loop Cloud Deployment Report Review "
        "(`uv run scripts/dev.py ai review cloud`). The human release decision is recorded "
        "separately in `docs/release-2/evidence/cloud/release-decision.md`.",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the cloud deployment report.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--stage",
        action="append",
        default=[],
        metavar="NAME=OUTCOME",
        help=f"Stage outcome; NAME is one of {', '.join(STAGE_ORDER)}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        stages = parse_stages(arguments.stage)
    except ValueError as exc:
        print(str(exc))
        return 2
    evidence = collect(arguments.log_dir, stages=stages, environment=os.environ)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    markdown = arguments.output_dir / "cloud-deployment-report.md"
    markdown.write_text(render(evidence), encoding="utf-8")
    (arguments.output_dir / "cloud-deployment-report.json").write_text(
        json.dumps(evidence.as_json(), indent=2) + "\n", encoding="utf-8"
    )
    print(f"{evidence.verdict}: wrote {markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
