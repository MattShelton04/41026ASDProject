"""Release 2 agentic-loop review modes: collectors, loop paths, reports, logs and decisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from flask import Flask
from scripts import dev
from scripts.devtools.review import cli as review_cli
from scripts.devtools.review.bounded import EvidenceReader
from scripts.devtools.review.deterministic import deterministic_review
from scripts.devtools.review.loop import (
    PROMPT_ROOT,
    AiModeReviewClient,
    ReviewLoopError,
    objective_for,
    project_detail,
)
from scripts.devtools.review.render import read_log
from scripts.devtools.review.workflow import (
    collect_bundle,
    record_release_decision,
    run_review,
)
from scripts.devtools.service_auth import AI_SERVICE_TOKEN_HEADER, protect_entry
from scripts.tests import review_fixtures as fixtures

from agent_core import AgentRunner, ModelMetrics, StructuredModelResult, ToolRegistry
from ai_mode import create_app
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.model_registry import load_model_registry
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.release_review import (
    ReviewCompletionValidator,
    ReviewEvidenceToolExecutor,
    review_evidence_definition,
)
from ai_mode.services import AppServices, UnconfiguredToolExecutor
from shared_contracts.evidence_review import (
    MAX_REVIEW_OBJECTIVE_CHARS,
    CheckStatus,
    EvidenceReviewBundle,
    InputStatus,
    ReviewMode,
    ReviewVerdict,
)
from shared_testkit import ScriptedLLMProvider

TOKEN = "t" * 40
FIXED_NOW = datetime(2026, 10, 20, 4, 0, tzinfo=UTC)


def _now() -> datetime:
    return FIXED_NOW


def _checks(bundle: EvidenceReviewBundle) -> dict[str, CheckStatus]:
    return {check.id: check.status for check in bundle.checks}


def _failed(bundle: EvidenceReviewBundle) -> set[str]:
    return {check.id for check in bundle.checks if check.status is CheckStatus.FAILED}


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    return fixtures.write_evidence(tmp_path / "evidence")


# --------------------------------------------------------------------------- collectors


def test_complete_multi_agent_evidence_passes_every_check(evidence: Path) -> None:
    bundle = collect_bundle("multi-agent", evidence)

    assert _failed(bundle) == set()
    assert bundle.checklist_verdict() is ReviewVerdict.PASS
    assert len(bundle.inputs) == 10
    assert all(item.status is InputStatus.READ and item.sha256 for item in bundle.inputs)
    totals = bundle.facts["totals"]
    assert totals == {
        "students_with_evidence": 5,
        "runs": 5,
        "runs_with_human_decision": 5,
        "tool_calls": 5,
    }


def test_multi_agent_review_reports_workflow_defects(evidence: Path) -> None:
    student_1 = evidence / "multi-agent" / "student-1"
    broken = fixtures.history("student-1")
    broken[2]["from_state"] = "planning"  # working -> reviewing recorded from the wrong state
    fixtures.write_jsonl(student_1 / "workflow_history.jsonl", broken)
    fixtures.write_jsonl(
        evidence / "multi-agent" / "student-2" / "coordination_audit.jsonl",
        fixtures.audit("student-2", tool="market.listings.delete.v1"),
    )
    undecided = fixtures.history("student-3")[:4]
    fixtures.write_jsonl(evidence / "multi-agent/student-3/workflow_history.jsonl", undecided)
    audit_3 = [item for item in fixtures.audit("student-3") if item["event"] != "decision.recorded"]
    fixtures.write_jsonl(evidence / "multi-agent/student-3/coordination_audit.jsonl", audit_3)
    no_handoffs = [item for item in fixtures.audit("student-4") if item["event"] != "agent.handoff"]
    fixtures.write_jsonl(evidence / "multi-agent/student-4/coordination_audit.jsonl", no_handoffs)
    (evidence / "multi-agent/student-5/coordination_audit.jsonl").unlink()

    bundle = collect_bundle("multi-agent", evidence)
    failed = _failed(bundle)

    assert "student-1.transitions" in failed
    assert "student-2.tool-allowlist" in failed
    assert "student-3.human-decision" in failed
    assert "student-3.stages" not in failed  # awaiting_human was reached through every stage
    assert "student-4.handoffs" in failed
    assert "student-4.handoffs" not in {c.id for c in bundle.checks if c.required}
    assert {"student-5.evidence", "student-5.correlation"} <= failed
    missing = {item.path: item.status for item in bundle.inputs}
    assert missing["multi-agent/student-5/coordination_audit.jsonl"] is InputStatus.MISSING
    assert bundle.checklist_verdict() is ReviewVerdict.FAIL


def test_multi_agent_requires_a_recorded_allowlist(evidence: Path) -> None:
    unlisted = fixtures.audit("student-1")
    unlisted[0]["detail"] = {"template_id": "student-1-review"}
    fixtures.write_jsonl(evidence / "multi-agent/student-1/coordination_audit.jsonl", unlisted)
    fixtures.write_json(
        evidence / "multi-agent/student-2/template.json",
        {"id": "student-2-review", "allowed_tools": list(fixtures.TOOLS["student-2"])},
    )

    bundle = collect_bundle("multi-agent", evidence)
    detail = {check.id: check.detail for check in bundle.checks}

    assert "student-1.tool-allowlist" in _failed(bundle)
    assert "allowed_tools" in detail["student-1.tool-allowlist"]
    assert "student-2.tool-allowlist" not in _failed(bundle)
    assert bundle.facts["students"]["student-2"]["templates"] == ["student-2-review"]  # type: ignore[index,call-overload]


def test_invalid_jsonl_is_an_evidence_gap_not_a_crash(evidence: Path) -> None:
    path = evidence / "multi-agent/student-1/workflow_history.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")

    bundle = collect_bundle("multi-agent", evidence)
    statuses = {item.path: item for item in bundle.inputs}

    assert statuses["multi-agent/student-1/workflow_history.jsonl"].status is InputStatus.INVALID
    assert "invalid JSON on line 6" in str(
        statuses["multi-agent/student-1/workflow_history.jsonl"].detail
    )
    assert "student-1.evidence" in _failed(bundle)


def test_complete_testing_evidence_passes_with_an_accepted_dependency_risk(
    evidence: Path,
) -> None:
    bundle = collect_bundle("testing", evidence)

    assert _failed(bundle) == {"security.dependencies-clean"}
    assert bundle.checklist_verdict() is ReviewVerdict.PASS_WITH_RISKS
    assert bundle.facts["ci"]["student-3"]["passing_tests"] == 2  # type: ignore[index,call-overload]
    assert bundle.facts["security"]["dependencies"] == {  # type: ignore[index,call-overload]
        "scanned": 3,
        "vulnerable": 1,
        "unexplained": 0,
    }


def test_testing_review_flags_unexplained_findings_and_red_ci(evidence: Path) -> None:
    ruff = json.loads((evidence / "security/ruff-security.json").read_text(encoding="utf-8"))
    ruff.append({"code": "S105", "filename": "student-2/backend/app.py", "location": {"row": 9}})
    fixtures.write_json(evidence / "security/ruff-security.json", ruff)
    secrets = json.loads((evidence / "security/detect-secrets.json").read_text(encoding="utf-8"))
    secrets["results"]["student-4/.env.example"] = [
        {"type": "Base64 High Entropy String", "line_number": 3, "is_verified": False}
    ]
    fixtures.write_json(evidence / "security/detect-secrets.json", secrets)
    audit = json.loads((evidence / "security/pip-audit.json").read_text(encoding="utf-8"))
    audit["dependencies"].append(
        {"name": "jinja2", "version": "3.1.4", "vulns": [{"id": "GHSA-q2x7-8rv6-6q7h"}]}
    )
    fixtures.write_json(evidence / "security/pip-audit.json", audit)
    fixtures.write_ci(evidence, "student-2", run=7, conclusion="failure")
    fixtures.write_ci(evidence, "student-4", run=8, outcomes=("passed", "failed"))
    (evidence / "ci/student-5.md").unlink()

    bundle = collect_bundle("testing", evidence)
    failed = _failed(bundle)
    details = {check.id: check.detail for check in bundle.checks}

    assert {"security.ruff", "security.secrets", "security.dependencies"} <= failed
    assert "S105" in details["security.ruff"]
    assert "unaudited: student-4/.env.example:3" in details["security.secrets"]
    assert "jinja2" in details["security.dependencies"]
    assert "ci.student-2.green" in failed
    assert {"ci.student-4.endpoints", "ci.student-4.junit"} <= failed
    assert {"ci.student-5.run", "ci.student-5.green", "ci.student-5.endpoints"} <= failed
    assert "ci.student-1.endpoints" not in failed


def test_oversize_evidence_is_hashed_but_not_parsed(evidence: Path) -> None:
    path = evidence / "security/ruff-security.json"
    path.write_text("[" + ",".join(["{}"] * 600_000) + "]", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    bundle = collect_bundle("testing", evidence)
    item = next(item for item in bundle.inputs if item.path == "security/ruff-security.json")

    assert item.status is InputStatus.OVERSIZE
    assert item.sha256 == digest
    assert item.bytes == path.stat().st_size
    assert "security.ruff" in _failed(bundle)


def test_reader_refuses_paths_outside_the_evidence_root(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    (tmp_path / "root").mkdir()
    reader = EvidenceReader(tmp_path / "root", max_total_bytes=10)

    escaped = reader.read_text("../secret.txt")
    absolute = reader.read_text((tmp_path / "secret.txt").as_posix())

    assert escaped.status is InputStatus.INVALID
    assert absolute.status is InputStatus.INVALID
    assert all(item.sha256 is None for item in reader.inputs)
    (tmp_path / "root" / "big.md").write_text("x" * 20, encoding="utf-8")
    assert reader.read_text("big.md").status is InputStatus.OVERSIZE


def test_reader_reports_symlinks_without_following_them(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    try:
        (root / "link.md").symlink_to(tmp_path / "outside.md")
    except OSError:
        pytest.skip("symbolic links are not permitted on this host")

    loaded = EvidenceReader(root).read_text("link.md")

    assert loaded.status is InputStatus.INVALID
    assert loaded.text is None


def test_complete_cloud_evidence_passes(evidence: Path) -> None:
    bundle = collect_bundle("cloud", evidence)

    assert _failed(bundle) == set()
    assert bundle.facts["crud"] == dict.fromkeys(fixtures.STUDENTS, "passed")
    assert "cloud/release-decision.md" not in {item.path for item in bundle.inputs}


def test_cloud_review_flags_failed_crud_ai_images_and_log_secrets(evidence: Path) -> None:
    value = fixtures.smoke(ai_enabled=True)
    checks = value["checks"]
    assert isinstance(checks, list)
    checks[2]["passed"] = False
    images = value["images"]
    assert isinstance(images, dict)
    images["f3-backend"] = "psg20acr.azurecr.io/propertyscope/f3-backend:latest"
    fixtures.write_json(evidence / "cloud/smoke.json", value)
    log = evidence / "cloud/logs/deploy.log"
    log.write_text(
        log.read_text(encoding="utf-8")
        + "##[error]Process completed with exit code 1.\n"
        + "token ghp_"
        + "a" * 36
        + "\n",
        encoding="utf-8",
    )

    bundle = collect_bundle("cloud", evidence)
    failed = _failed(bundle)

    assert {
        "cloud.smoke",
        "cloud.crud.student-2",
        "cloud.ai-disabled",
        "cloud.images",
        "cloud.workflow",
        "cloud.log-secrets",
    } <= failed
    assert "cloud.crud.student-1" not in failed
    refs = {check.id: check.evidence_refs for check in bundle.checks}
    assert "cloud/logs/deploy.log#line-5" in refs["cloud.workflow"]


@pytest.mark.parametrize("mode", ["multi-agent", "testing", "cloud"])
def test_missing_evidence_is_reported_as_gaps(tmp_path: Path, mode: ReviewMode) -> None:
    bundle = collect_bundle(mode, tmp_path / "absent")

    assert bundle.checklist_verdict() is ReviewVerdict.FAIL
    assert bundle.inputs
    assert all(item.status is InputStatus.MISSING for item in bundle.inputs)
    assert any("Evidence gap" in check.detail for check in bundle.checks)


# --------------------------------------------------------------------------- deterministic loop


@pytest.mark.parametrize(
    ("mode", "verdict"),
    [
        ("multi-agent", ReviewVerdict.PASS),
        ("testing", ReviewVerdict.PASS_WITH_RISKS),
        ("cloud", ReviewVerdict.PASS),
    ],
)
def test_deterministic_review_writes_report_and_log(
    evidence: Path, tmp_path: Path, mode: ReviewMode, verdict: ReviewVerdict
) -> None:
    out = tmp_path / "reviews"

    result = run_review(mode, evidence_dir=evidence, out_dir=out, deterministic=True, now=_now)

    record = result.record
    assert record.verdict is verdict
    assert record.engine == "deterministic"
    assert record.provider == "deterministic-review"
    assert record.phases == ("plan", "act", "observe", "adapt")
    assert record.prompt_set == f"review-{mode}.v1"
    assert any(f"review-{mode}/v1" in prompt for prompt in record.prompts)
    report = result.report_path.read_text(encoding="utf-8")
    assert report.startswith("# ")
    assert f"| Verdict | **{verdict.value}** |" in report
    assert "deterministic checklist decisions" in report
    for item in record.bundle.inputs:
        assert f"`{item.sha256}`" in report
    entries = read_log(result.log_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == "review_completed"
    assert entry["run_id"] == record.run_id
    assert entry["prompt_set"] == f"review-{mode}.v1"
    assert entry["verdict"] == verdict.value
    assert entry["report_sha256"] == hashlib.sha256(result.report_path.read_bytes()).hexdigest()
    assert len(entry["checks"]) == len(record.bundle.checks)  # type: ignore[arg-type]
    assert entry["tool_evidence"]

    run_review(mode, evidence_dir=evidence, out_dir=out, deterministic=True, now=_now)
    assert len(read_log(result.log_path)) == 2


def test_deterministic_review_of_missing_evidence_fails_with_findings(tmp_path: Path) -> None:
    result = run_review(
        "testing", evidence_dir=tmp_path / "none", out_dir=tmp_path / "out", deterministic=True
    )

    assert result.record.verdict is ReviewVerdict.FAIL
    assert len(result.record.output.findings) == len(_failed(result.record.bundle))
    assert result.record.output.recommendations
    assert "Evidence gap" in result.report_path.read_text(encoding="utf-8")


def test_deterministic_review_has_an_info_finding_when_everything_passes(evidence: Path) -> None:
    review = deterministic_review(collect_bundle("cloud", evidence))

    assert review.verdict is ReviewVerdict.PASS
    assert [finding.severity.value for finding in review.findings] == ["info"]
    assert review.recommendations == ()


def test_oversized_facts_are_compacted_to_fit_the_objective(evidence: Path) -> None:
    bundle = collect_bundle("multi-agent", evidence)
    padded = bundle.evolve(facts={"padding": "x" * (MAX_REVIEW_OBJECTIVE_CHARS + 10)})

    compact, objective = objective_for(padded)

    assert compact.compacted
    assert len(objective) <= MAX_REVIEW_OBJECTIVE_CHARS
    assert [check.id for check in compact.checks] == [check.id for check in bundle.checks]
    review = deterministic_review(compact)
    assert any("compacted" in risk.description for risk in review.risks)


# --------------------------------------------------------------------------- live AI-mode path


class _SynchronousQueue:
    def __init__(self) -> None:
        self.runner: AgentRunner | None = None

    def enqueue(self, run_id: UUID) -> None:
        assert self.runner is not None
        self.runner.run_until_blocked(run_id)


def _result(content: dict[str, Any]) -> StructuredModelResult:
    return StructuredModelResult(
        content=content,
        provider="openai",
        model="gpt-test",
        metrics=ModelMetrics(total_duration_ms=5),
    )


def _plan() -> StructuredModelResult:
    return _result(
        {
            "goal": "Review the evidence",
            "actions": [
                {
                    "sequence": 1,
                    "tool_name": "review.evidence.v1",
                    "arguments": {},
                    "purpose": "Read the bundle",
                }
            ],
            "success_criteria": ["Every failed check is assessed"],
            "risk_level": "low",
            "assumptions": [],
        }
    )


def _complete(final_result: dict[str, Any]) -> StructuredModelResult:
    return _result(
        {"decision": "complete", "justification": "Reviewed", "final_result": final_result}
    )


def _model_review(bundle: EvidenceReviewBundle) -> dict[str, Any]:
    review = deterministic_review(bundle).model_dump(mode="json")
    review["summary"] = "Model review of the attached evidence."
    review["risks"].append(
        {
            "severity": "low",
            "description": "Evidence was captured before the final freeze.",
            "mitigation": "Re-run the review after the feature freeze.",
        }
    )
    return review


@pytest.fixture
def fake_ai_mode(tmp_path: Path) -> Iterator[tuple[httpx.Client, AppServices]]:
    store = SQLiteRunStore(tmp_path / "ai-mode.sqlite3")
    store.initialize()
    queue = _SynchronousQueue()
    provider = ScriptedLLMProvider([])
    services = AppServices(
        store=store,
        provider=provider,
        queue=queue,
        clock=SystemClock(),
        ids=UUID4Generator(),
        default_model_profile=load_model_registry().default_profile,
        model_registry=load_model_registry(),
    )
    queue.runner = AgentRunner(
        store=store,
        provider=provider,
        prompt_builder=RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)),
        tools=ToolRegistry((review_evidence_definition(),)),
        tool_executor=ReviewEvidenceToolExecutor(UnconfiguredToolExecutor(), store),
        clock=SystemClock(),
        ids=UUID4Generator(),
        completion_validator=ReviewCompletionValidator(),
    )
    app: Flask = create_app(services=services)
    protect_entry(app, TOKEN)
    with httpx.Client(
        transport=httpx.WSGITransport(app=app), base_url="http://ai-mode.test"
    ) as client:
        yield client, services


def _script(services: AppServices, *outcomes: StructuredModelResult) -> None:
    provider = services.provider
    assert isinstance(provider, ScriptedLLMProvider)
    provider._outcomes.extend(outcomes)


def test_live_review_runs_through_ai_mode_and_records_the_run(
    evidence: Path, tmp_path: Path, fake_ai_mode: tuple[httpx.Client, AppServices]
) -> None:
    client, services = fake_ai_mode
    compact, _ = objective_for(collect_bundle("testing", evidence))
    _script(services, _plan(), _complete(_model_review(compact)))

    result = run_review(
        "testing",
        evidence_dir=evidence,
        out_dir=tmp_path / "reviews",
        deterministic=False,
        client=AiModeReviewClient("http://ai-mode.test", TOKEN, client=client),
        now=_now,
    )

    record = result.record
    assert record.engine == "ai-mode"
    assert (record.provider, record.model) == ("openai", "gpt-test")
    assert record.model_verdict is ReviewVerdict.PASS_WITH_RISKS
    assert record.model_output_valid is True
    stored = services.store.get(UUID(record.run_id or ""))
    assert stored is not None
    assert stored.run.feature_key == "agentic-loop"
    assert stored.run.prompt_set == "review-testing.v1"
    assert stored.run.title == "Release 2 testing evidence review"
    report = result.report_path.read_text(encoding="utf-8")
    assert "(AI-mode Activity history)" in report
    assert "Evidence was captured before the final freeze." in report
    entry = read_log(result.log_path)[-1]
    assert entry["engine"] == "ai-mode"
    assert entry["model"] == "gpt-test"
    assert entry["model_output_valid"] is True
    assert any(str(item).startswith("security/") for item in entry["tool_evidence"])  # type: ignore[union-attr]


def test_schema_invalid_model_output_fails_the_run_and_can_fall_back(
    evidence: Path, tmp_path: Path, fake_ai_mode: tuple[httpx.Client, AppServices]
) -> None:
    client, services = fake_ai_mode
    invalid = _complete({"summary": "Looks fine", "verdict": "pass", "findings": "none"})
    lenient = _complete({"summary": "Ship it", "verdict": "pass"})
    _script(services, _plan(), invalid, lenient, invalid)
    ai_client = AiModeReviewClient("http://ai-mode.test", TOKEN, client=client)

    with pytest.raises(RuntimeError, match="--deterministic"):
        run_review(
            "testing",
            evidence_dir=evidence,
            out_dir=tmp_path / "reviews",
            deterministic=False,
            client=ai_client,
        )

    _script(services, _plan(), invalid, invalid, invalid)
    result = run_review(
        "testing",
        evidence_dir=evidence,
        out_dir=tmp_path / "reviews",
        deterministic=False,
        client=ai_client,
        fallback=True,
    )

    assert result.record.engine == "deterministic-fallback"
    assert result.record.fallback_reason is not None
    assert result.record.fallback_reason.startswith("invalid_output")
    assert "**Fallback:**" in result.report_path.read_text(encoding="utf-8")
    events = [entry["event"] for entry in read_log(result.log_path)]
    assert events == ["review_unavailable", "review_unavailable", "review_completed"]


def test_cli_rejects_a_succeeded_run_whose_review_breaks_the_schema(
    evidence: Path, tmp_path: Path
) -> None:
    bundle, _ = objective_for(collect_bundle("cloud", evidence))
    run_id = "6f1c2b9e-1d7a-4d0f-9a43-0c7c2fbd1a11"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers[AI_SERVICE_TOKEN_HEADER] == TOKEN
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["prompt_set"] == "review-cloud.v1"
            assert body["tool_allowlist"] == ["review.evidence.v1"]
            assert EvidenceReviewBundle.model_validate_json(body["objective"]) == bundle
            return httpx.Response(202, json={"id": run_id})
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": run_id,
                    "status": "succeeded",
                    "request_id": "r",
                    "final_result": {
                        "summary": "ok",
                        "verdict": "pass",
                        "findings": [
                            {
                                "severity": "low",
                                "area": "cloud",
                                "message": "Invented evidence",
                                "evidence_refs": ["cloud/invented.md"],
                            }
                        ],
                    },
                },
                "steps": [],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="failed validation"):
        run_review(
            "cloud",
            evidence_dir=evidence,
            out_dir=tmp_path / "reviews",
            deterministic=False,
            client=AiModeReviewClient("http://ai-mode.test", TOKEN, client=client),
        )
    entry = read_log(tmp_path / "reviews/cloud-validation-log.jsonl")[-1]
    assert (entry["event"], entry["error_code"], entry["run_id"]) == (
        "review_unavailable",
        "invalid_output",
        run_id,
    )


def test_unreachable_and_slow_ai_mode_fail_clearly() -> None:
    bundle = EvidenceReviewBundle.model_validate(
        {
            "mode": "cloud",
            "inputs": [],
            "checks": [
                {"id": "cloud.report", "title": "t", "status": "failed", "detail": "missing"}
            ],
        }
    )

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    unreachable = AiModeReviewClient(
        "http://127.0.0.1:9", TOKEN, client=httpx.Client(transport=httpx.MockTransport(refuse))
    )
    with pytest.raises(ReviewLoopError, match="unreachable"):
        unreachable.run(bundle, timeout_seconds=1)

    def running(request: httpx.Request) -> httpx.Response:
        run = {"id": "6f1c2b9e-1d7a-4d0f-9a43-0c7c2fbd1a11", "status": "acting"}
        return httpx.Response(202 if request.method == "POST" else 200, json=run | {"run": run})

    clock = iter(range(100))
    slow = AiModeReviewClient(
        "http://ai-mode.test",
        TOKEN,
        client=httpx.Client(transport=httpx.MockTransport(running)),
        sleep=lambda _: None,
        monotonic=lambda: float(next(clock)),
    )
    with pytest.raises(ReviewLoopError) as raised:
        slow.run(bundle, timeout_seconds=3)
    assert raised.value.code == "timeout"
    assert raised.value.run_id == "6f1c2b9e-1d7a-4d0f-9a43-0c7c2fbd1a11"

    def unauthorised(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "unauthorized", "detail": "Service auth"})

    rejected = AiModeReviewClient(
        "http://ai-mode.test",
        TOKEN,
        client=httpx.Client(transport=httpx.MockTransport(unauthorised)),
    )
    with pytest.raises(ReviewLoopError) as denied:
        rejected.run(bundle, timeout_seconds=1)
    assert denied.value.code == "unauthorized"


def test_project_detail_requires_a_run_object() -> None:
    with pytest.raises(ReviewLoopError):
        project_detail({"steps": []}, engine="ai-mode")


# --------------------------------------------------------------------------- human decision


def test_human_release_decision_is_recorded_against_the_current_review(
    evidence: Path, tmp_path: Path
) -> None:
    out = tmp_path / "reviews"
    review = run_review("cloud", evidence_dir=evidence, out_dir=out, deterministic=True)
    assert "**Pending.**" in review.report_path.read_text(encoding="utf-8")

    path = record_release_decision(
        evidence_dir=evidence,
        out_dir=out,
        decision="release",
        decider="Matthew Shelton",
        rationale="All five CRUD cases passed with the AI tier off.",
        now=_now,
    )

    document = path.read_text(encoding="utf-8")
    assert path == evidence / "cloud" / "release-decision.md"
    assert "| Decision | **RELEASE** |" in document
    assert "| Decided by | Matthew Shelton |" in document
    assert review.record.review_id in document
    assert "All five CRUD cases passed" in document
    updated = review.report_path.read_text(encoding="utf-8")
    assert "**RELEASE** by Matthew Shelton at 2026-10-20T04:00:00Z" in updated
    assert "**Pending.**" not in updated
    decision = read_log(review.log_path)[-1]
    assert decision["event"] == "human_release_decision"
    assert decision["run_id"] == review.record.run_id
    assert decision["decision_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    # The decision file is output, not reviewed input, so it never invalidates the review.
    assert collect_bundle("cloud", evidence).inputs == review.record.bundle.inputs


def test_release_decision_guards(evidence: Path, tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    decide = {"evidence_dir": evidence, "out_dir": out, "decider": "Matthew", "rationale": "Why"}
    with pytest.raises(RuntimeError, match="No completed cloud review"):
        record_release_decision(decision="hold", **decide)  # type: ignore[arg-type]

    fixtures.write_json(evidence / "cloud/smoke.json", fixtures.smoke(ai_enabled=True))
    run_review("cloud", evidence_dir=evidence, out_dir=out, deterministic=True)
    with pytest.raises(RuntimeError, match="acknowledge-failed-review"):
        record_release_decision(decision="release", **decide)  # type: ignore[arg-type]
    record_release_decision(decision="hold", **decide)  # type: ignore[arg-type]
    overridden = record_release_decision(
        decision="release",
        acknowledge_failed_review=True,
        **decide,  # type: ignore[arg-type]
    )
    assert "| Overrode a failed review | yes |" in overridden.read_text(encoding="utf-8")

    fixtures.write_json(evidence / "cloud/smoke.json", fixtures.smoke())
    with pytest.raises(RuntimeError, match="changed since review"):
        record_release_decision(decision="hold", **decide)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="--decider"):
        record_release_decision(
            evidence_dir=evidence, out_dir=out, decision="hold", decider=" ", rationale="r"
        )
    with pytest.raises(RuntimeError, match="--decision"):
        record_release_decision(
            evidence_dir=evidence, out_dir=out, decision="ship", decider="M", rationale="r"
        )


# --------------------------------------------------------------------------- CLI


def test_cli_runs_each_mode_and_records_a_decision(evidence: Path, capsys: Any) -> None:
    out = evidence / "reviews"
    for mode in ("multi-agent", "testing", "cloud"):
        code = dev.main(["ai", "review", mode, "--deterministic", "--evidence-dir", str(evidence)])
        assert code == 0
        assert (out / f"{mode}-review.md").is_file()
        assert (out / f"{mode}-validation-log.jsonl").is_file()
    code = dev.main(
        [
            "ai",
            "review",
            "decide",
            "--decision",
            "release",
            "--decider",
            "Matthew",
            "--rationale",
            "Smoke passed",
            "--evidence-dir",
            str(evidence),
        ]
    )
    assert code == 0
    assert "Recorded the release decision" in capsys.readouterr().out


def test_cli_returns_one_for_a_failed_review(tmp_path: Path) -> None:
    code = dev.main(
        ["ai", "review", "cloud", "--deterministic", "--evidence-dir", str(tmp_path / "e")]
    )

    assert code == 1
    assert (tmp_path / "e/reviews/cloud-review.md").is_file()


def test_cli_live_mode_needs_ai_mode_outside_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("CI", "true")
    assert dev.main(["ai", "review", "testing", "--evidence-dir", str(tmp_path)]) == 1
    assert "--deterministic" in capsys.readouterr().err

    monkeypatch.delenv("CI")
    monkeypatch.delenv("AI_MODE_SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(review_cli.host_runtime, "HOST_DIRECTORY", tmp_path / "host")
    assert dev.main(["ai", "review", "testing", "--evidence-dir", str(tmp_path)]) == 1
    assert "no service token" in capsys.readouterr().err

    monkeypatch.setenv("AI_MODE_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("AI_MODE_PORT", "9")
    assert (
        dev.main(["ai", "review", "testing", "--evidence-dir", str(tmp_path), "--timeout", "1"])
        == 1
    )
    error = capsys.readouterr().err
    assert "could not use AI-mode" in error
    assert "unreachable" in error
