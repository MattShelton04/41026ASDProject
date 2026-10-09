"""Orchestrate one review mode end to end, and record the human release decision."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue, ValidationError

from scripts.devtools.config import REPOSITORY_ROOT
from scripts.devtools.review import DECISIONS, cloud, multi_agent, testing
from scripts.devtools.review.bounded import EvidenceReader
from scripts.devtools.review.loop import (
    AiModeReviewClient,
    LoopRun,
    ReviewLoopError,
    bundle_digest,
    objective_for,
    run_deterministic,
)
from scripts.devtools.review.render import (
    LOG_SCHEMA_VERSION,
    ReviewRecord,
    append_log,
    log_entry,
    read_log,
    render_report,
    replace_decision_block,
    table,
)
from shared_contracts.evidence_review import (
    REVIEW_PROMPT_SETS,
    EvidenceReviewBundle,
    EvidenceReviewOutput,
    ReviewMode,
    ReviewVerdict,
    stricter_verdict,
    validate_review_output,
)

COLLECTORS: Mapping[ReviewMode, Callable[[EvidenceReader], EvidenceReviewBundle]] = {
    "multi-agent": multi_agent.collect,
    "testing": testing.collect,
    "cloud": cloud.collect,
}
ENGINE_LABELS = {
    "ai-mode": "AI-mode run through the shared agent loop with the configured model provider",
    "deterministic": "Production agent loop in-process with deterministic checklist decisions "
    "(--deterministic; no model)",
    "deterministic-fallback": "Deterministic checklist fallback after the AI-mode review failed "
    "(--fallback-deterministic; no model)",
}
DECISION_HINT = (
    "**Pending.** A named human records the release decision with `uv run scripts/dev.py ai "
    "review decide --decision release|hold|rollback --decider NAME --rationale TEXT`; it is "
    "written to `cloud/release-decision.md` and appended to this mode's validation log."
)


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Paths written by one review and its record."""

    record: ReviewRecord
    report_path: Path
    log_path: Path


def collect_bundle(mode: ReviewMode, evidence_dir: Path) -> EvidenceReviewBundle:
    """Collect one mode's bounded evidence; missing evidence becomes failed checks."""
    return COLLECTORS[mode](EvidenceReader(evidence_dir))


def run_review(
    mode: ReviewMode,
    *,
    evidence_dir: Path,
    out_dir: Path,
    deterministic: bool,
    client: AiModeReviewClient | None = None,
    timeout_seconds: float = 300,
    fallback: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ReviewResult:
    """Collect, review through the loop, validate, then write the report and log entry."""
    started_at, started = now(), time.monotonic()
    review_id = str(uuid.uuid4())
    log_path = out_dir / f"{mode}-validation-log.jsonl"
    bundle = collect_bundle(mode, evidence_dir)
    digest = bundle_digest(bundle)
    compact, _ = objective_for(bundle)
    fallback_reason: str | None = None
    model_verdict: ReviewVerdict | None = None
    validation = "validated by the deterministic loop's completion validator"
    if deterministic:
        engine, loop, output = "deterministic", *_deterministic(compact, timeout_seconds)
    else:
        if client is None:
            raise RuntimeError("A live review needs an AI-mode client; pass --deterministic")
        try:
            loop = client.run(compact, timeout_seconds=timeout_seconds)
            output = _validated_output(loop, compact)
            engine, model_verdict = "ai-mode", output.verdict
            validation = "passed (validated by AI-mode and again by the loop CLI)"
        except ReviewLoopError as exc:
            append_log(log_path, _unavailable_entry(mode, review_id, digest, bundle, exc, now()))
            if not fallback:
                raise RuntimeError(
                    f"The {mode} review could not use AI-mode: {exc}. Start the host AI services "
                    "with `uv run scripts/dev.py ai start` and a provider key, or rerun with "
                    "--deterministic (checklist only) or --fallback-deterministic."
                ) from exc
            fallback_reason = f"{exc.code}: {exc}"
            if exc.run_id:
                fallback_reason += f" (AI-mode run {exc.run_id})"
            engine, loop, output = (
                "deterministic-fallback",
                *_deterministic(compact, timeout_seconds),
            )
    checklist = bundle.checklist_verdict()
    record = ReviewRecord(
        review_id=review_id,
        mode=mode,
        prompt_set=REVIEW_PROMPT_SETS[mode],
        engine=engine,
        engine_label=ENGINE_LABELS[engine],
        run_id=loop.run_id,
        request_id=loop.request_id,
        provider=loop.provider,
        model=loop.model,
        prompts=tuple(
            dict.fromkeys(
                f"{item.get('phase')}: {item.get('prompt_id')}/{item.get('prompt_version')}"
                for item in loop.invocations
            )
        ),
        started_at=_iso(started_at),
        finished_at=_iso(now()),
        duration_ms=int((time.monotonic() - started) * 1000),
        evidence_root=_display(evidence_dir),
        bundle=bundle,
        bundle_sha256=digest,
        objective_compacted=compact.compacted,
        output=output,
        model_verdict=model_verdict,
        checklist_verdict=checklist,
        verdict=stricter_verdict(output.verdict, checklist),
        model_output_valid=True if engine == "ai-mode" else None,
        validation_detail=(
            validation if engine != "deterministic-fallback" else "not applicable (fallback)"
        ),
        fallback_reason=fallback_reason,
        phases=loop.phases,
        tool_evidence=loop.tool_evidence,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{mode}-review.md"
    report = render_report(
        record, log_name=log_path.name, decision_hint=DECISION_HINT if mode == "cloud" else None
    )
    report_path.write_text(report, encoding="utf-8", newline="\n")
    append_log(
        log_path,
        log_entry(
            record,
            report_path=_display(report_path),
            report_sha256=hashlib.sha256(report.encode("utf-8")).hexdigest(),
        ),
    )
    return ReviewResult(record=record, report_path=report_path, log_path=log_path)


def _deterministic(
    bundle: EvidenceReviewBundle, timeout_seconds: float
) -> tuple[LoopRun, EvidenceReviewOutput]:
    loop = run_deterministic(bundle, time_budget_ms=int(timeout_seconds * 1000))
    if loop.status != "succeeded":
        raise RuntimeError(f"The deterministic review loop ended {loop.status}: {loop.error}")
    return loop, _validated_output(loop, bundle)


def _validated_output(loop: LoopRun, bundle: EvidenceReviewBundle) -> EvidenceReviewOutput:
    if loop.status != "succeeded":
        raise ReviewLoopError(
            f"AI-mode run {loop.run_id} ended {loop.status}"
            + (f" ({loop.error})" if loop.error else ""),
            run_id=loop.run_id,
            code="invalid_output" if loop.error and "validation" in loop.error else "run_failed",
        )
    try:
        output = EvidenceReviewOutput.model_validate(loop.final_result)
        return validate_review_output(output, bundle)
    except (ValidationError, ValueError) as exc:
        reason = (
            f"{exc.error_count()} schema error(s)" if isinstance(exc, ValidationError) else str(exc)
        )
        raise ReviewLoopError(
            f"AI-mode run {loop.run_id} returned a review that failed validation: {reason}",
            run_id=loop.run_id,
            code="invalid_output",
        ) from exc


def _unavailable_entry(
    mode: str,
    review_id: str,
    digest: str,
    bundle: EvidenceReviewBundle,
    exc: ReviewLoopError,
    at: datetime,
) -> dict[str, JsonValue]:
    return {
        "schema_version": LOG_SCHEMA_VERSION,
        "event": "review_unavailable",
        "review_id": review_id,
        "mode": mode,
        "prompt_set": REVIEW_PROMPT_SETS[bundle.mode],
        "run_id": exc.run_id,
        "error_code": exc.code,
        "error": str(exc)[:500],
        "at": _iso(at),
        "bundle_sha256": digest,
        "inputs": [
            {"path": item.path, "status": item.status.value, "sha256": item.sha256}
            for item in bundle.inputs
        ],
        "checklist_verdict": bundle.checklist_verdict().value,
    }


def record_release_decision(
    *,
    evidence_dir: Path,
    out_dir: Path,
    decision: str,
    decider: str,
    rationale: str,
    acknowledge_failed_review: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Path:
    """Record a named human's decision against the latest, still-current cloud review."""
    if decision not in DECISIONS:
        raise RuntimeError(f"--decision must be one of {', '.join(DECISIONS)}")
    decider = decider.strip()
    rationale = rationale.strip()
    if not decider or len(decider) > 100 or any(ord(char) < 32 for char in decider):
        raise RuntimeError("--decider must be a person's name of 1-100 printable characters")
    if not rationale or len(rationale) > 2000:
        raise RuntimeError("--rationale must contain 1-2000 characters")
    log_path = out_dir / "cloud-validation-log.jsonl"
    reviews = [
        entry
        for entry in read_log(log_path)
        if entry.get("event") == "review_completed" and entry.get("mode") == "cloud"
    ]
    if not reviews:
        raise RuntimeError(
            "No completed cloud review was found; run `uv run scripts/dev.py ai review cloud` first"
        )
    latest = reviews[-1]
    current = collect_bundle("cloud", evidence_dir)
    changed = _changed_inputs(latest.get("inputs"), current)
    if changed:
        raise RuntimeError(
            f"Cloud evidence changed since review {latest.get('review_id')}: "
            + ", ".join(changed[:5])
            + ". Re-run `uv run scripts/dev.py ai review cloud` before deciding."
        )
    verdict = str(latest.get("verdict"))
    if decision == "release" and verdict == "fail" and not acknowledge_failed_review:
        raise RuntimeError(
            "The latest cloud review verdict is fail. Hold or roll back, or pass "
            "--acknowledge-failed-review to record a release that overrides it."
        )
    decided_at = _iso(now())
    decision_path = evidence_dir / "cloud" / "release-decision.md"
    review_path = out_dir / "cloud-review.md"
    link = _relative(review_path, decision_path.parent)
    rows = [
        ("Decision", f"**{decision.upper()}**"),
        ("Decided by", decider.replace("|", "\\|")),
        ("Decided at", decided_at),
        ("Cloud review", f"[{review_path.name}]({link})"),
        ("Review ID", f"`{latest.get('review_id')}`"),
        ("Loop run ID", f"`{latest.get('run_id')}` ({latest.get('engine')})"),
        ("Review verdict", str(verdict)),
        ("Prompt set", f"`{latest.get('prompt_set')}`"),
        ("Evidence bundle SHA-256", f"`{latest.get('bundle_sha256')}`"),
        (
            "Overrode a failed review",
            "yes" if verdict == "fail" and decision == "release" else "no",
        ),
    ]
    inputs = latest.get("inputs")
    evidence_rows = [
        f"| `{item.get('path')}` | {item.get('status')} | `{item.get('sha256')}` |"
        for item in (inputs if isinstance(inputs, list) else [])
        if isinstance(item, dict)
    ]
    document = "\n".join(
        [
            "# Release decision",
            "",
            "Recorded with `uv run scripts/dev.py ai review decide`. The agentic loop's Cloud "
            "Deployment Report Review informed this decision; the named person made it.",
            "",
            *table(rows),
            "",
            "## Rationale",
            "",
            rationale,
            "",
            "## Evidence reviewed",
            "",
            "| Path | Status | SHA-256 |",
            "|---|---|---|",
            *(evidence_rows or ["| none | | |"]),
            "",
        ]
    )
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(document, encoding="utf-8", newline="\n")
    append_log(
        log_path,
        {
            "schema_version": LOG_SCHEMA_VERSION,
            "event": "human_release_decision",
            "review_id": latest.get("review_id"),
            "run_id": latest.get("run_id"),
            "mode": "cloud",
            "decision": decision,
            "decider": decider,
            "decided_at": decided_at,
            "review_verdict": verdict,
            "overrode_failed_review": verdict == "fail" and decision == "release",
            "rationale": rationale,
            "bundle_sha256": latest.get("bundle_sha256"),
            "decision_path": _display(decision_path),
            "decision_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        },
    )
    if review_path.is_file():
        block = (
            f"**{decision.upper()}** by {decider} at {decided_at} for review "
            f"`{latest.get('review_id')}`. Rationale: {' '.join(rationale.split())} "
            f"Recorded in `{_relative(decision_path, review_path.parent)}`."
        )
        report = review_path.read_text(encoding="utf-8")
        review_path.write_text(
            replace_decision_block(report, block), encoding="utf-8", newline="\n"
        )
    return decision_path


def _changed_inputs(logged: JsonValue | None, current: EvidenceReviewBundle) -> list[str]:
    before: dict[str, tuple[object, object]] = {}
    if isinstance(logged, list):
        for item in logged:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                before[str(item["path"])] = (item.get("status"), item.get("sha256"))
    after = {item.path: (item.status.value, item.sha256) for item in current.inputs}
    return sorted(
        path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _relative(target: Path, start: Path) -> str:
    try:
        return Path(os.path.relpath(target.resolve(), start.resolve())).as_posix()
    except ValueError:  # Different Windows drives have no relative path.
        return target.resolve().as_posix()
