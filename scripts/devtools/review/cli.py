"""``dev.py ai review`` command registration and dispatch."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from scripts.devtools import host_runtime
from scripts.devtools.review import DECISIONS, DEFAULT_EVIDENCE_DIR
from scripts.devtools.service_auth import validate_service_token
from shared_contracts.evidence_review import REVIEW_MODES, ReviewMode

MODE_HELP = {
    "multi-agent": "Multi-Agent Workflow Review of exported workflow histories and audits",
    "testing": "Testing Report Review of pre-commit security scans and CI endpoint results",
    "cloud": "Cloud Deployment Report Review supporting the human release decision",
}


def add_review_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``ai review {multi-agent,testing,cloud,decide}``."""
    review = commands.add_parser(
        "review", help="Review Release 2 evidence through the agentic loop (R2-20 to R2-23)"
    )
    modes = review.add_subparsers(dest="review_mode", required=True)
    for mode in REVIEW_MODES:
        command = modes.add_parser(mode, help=MODE_HELP[mode])
        _add_location_options(command)
        command.add_argument(
            "--deterministic",
            action="store_true",
            help="Run the production loop in-process with checklist decisions (no model; CI-safe)",
        )
        command.add_argument(
            "--fallback-deterministic",
            action="store_true",
            help="If AI-mode is unavailable or its review is invalid, write a clearly "
            "labelled deterministic review instead of failing",
        )
        command.add_argument(
            "--ai-mode-url",
            default=None,
            help="AI-mode base URL (default: http://127.0.0.1:$AI_MODE_PORT)",
        )
        command.add_argument(
            "--timeout",
            type=float,
            default=300.0,
            help="Seconds to wait for the AI-mode review run (default: 300)",
        )
    decide = modes.add_parser(
        "decide", help="Record the human release decision for the latest cloud review"
    )
    _add_location_options(decide)
    decide.add_argument("--decision", choices=DECISIONS, required=True)
    decide.add_argument("--decider", required=True, help="Name of the person deciding")
    decide.add_argument("--rationale", required=True, help="Why; recorded verbatim")
    decide.add_argument(
        "--acknowledge-failed-review",
        action="store_true",
        help="Required to record a release over a failed cloud review",
    )


def _add_location_options(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="Evidence root (default: docs/release-2/evidence)",
    )
    command.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Review output directory (default: <evidence-dir>/reviews)",
    )
    command.add_argument(
        "--env-file",
        type=Path,
        help="Load AI-mode port and token settings from this dotenv file",
    )


def run(arguments: argparse.Namespace, environment: Mapping[str, str]) -> int:
    """Execute one review command; returns 1 when the review verdict is fail."""
    # The loop, collectors and AI-mode packages load only when a review actually runs.
    from scripts.devtools.review.loop import AiModeReviewClient
    from scripts.devtools.review.workflow import record_release_decision, run_review

    evidence_dir = cast(Path, arguments.evidence_dir)
    out_dir = cast(Path | None, arguments.out) or evidence_dir / "reviews"
    if arguments.review_mode == "decide":
        path = record_release_decision(
            evidence_dir=evidence_dir,
            out_dir=out_dir,
            decision=arguments.decision,
            decider=arguments.decider,
            rationale=arguments.rationale,
            acknowledge_failed_review=arguments.acknowledge_failed_review,
        )
        print(f"Recorded the {arguments.decision} decision in {path}", flush=True)
        return 0
    mode = cast(ReviewMode, arguments.review_mode)
    client: AiModeReviewClient | None = None
    if not arguments.deterministic:
        if environment.get("CI", "").lower() in {"true", "1"}:
            raise RuntimeError("AI-mode stays disabled in CI; run the review with --deterministic")
        client = AiModeReviewClient(
            arguments.ai_mode_url or host_runtime.local_url("ai-mode", environment),
            _service_token(environment),
        )
    try:
        result = run_review(
            mode,
            evidence_dir=evidence_dir,
            out_dir=out_dir,
            deterministic=arguments.deterministic,
            client=client,
            timeout_seconds=arguments.timeout,
            fallback=arguments.fallback_deterministic,
        )
    finally:
        if client is not None:
            client.close()
    record = result.record
    print(
        f"{mode} review {record.verdict.value} ({record.engine}, run {record.run_id}); "
        f"{len(record.bundle.checks)} checks, {len(record.output.findings)} findings.\n"
        f"Report: {result.report_path}\nLog: {result.log_path}",
        flush=True,
    )
    return 1 if record.verdict.value == "fail" else 0


def _service_token(environment: Mapping[str, str]) -> str:
    """Read the managed AI-mode credential without creating one for a stopped service."""
    token = environment.get("AI_MODE_SERVICE_TOKEN", "")
    path = host_runtime.HOST_DIRECTORY / "ai-mode.token"
    if not token and path.is_file():
        token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(
            "AI-mode has no service token in this checkout; start it with "
            "`uv run scripts/dev.py ai start`, or run the review with --deterministic"
        )
    validate_service_token(token)
    return token
