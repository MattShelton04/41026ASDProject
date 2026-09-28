"""Keep the screenshot capture list and the Release 1 report in step."""

from __future__ import annotations

import re

from scripts import build_release1_report as report
from scripts import capture_release1_screenshots as capture


def test_every_report_screenshot_has_a_capture_entry() -> None:
    source = report.SOURCE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"assets/release-1/screenshots/([\w-]+)\.png", source))
    names = {shot.name for shot in capture.SHOTS}
    assert referenced == names


def test_assistant_shots_that_are_ready_ask_a_question() -> None:
    for shot in capture.SHOTS:
        if shot.path.endswith("#assistant") and not shot.pending:
            assert shot.question, shot.name


def test_list_marks_pending_shots(capsys) -> None:  # type: ignore[no-untyped-def]
    # A feature that has not adopted the shared assistant and a corpus yet; features adopt
    # independently, so this must name one that is still pending rather than the first adopter.
    assert capture.main(["--list", "--only", "feature-4"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert all("pending" in line for line in lines)


def test_list_marks_adopted_shots_ready(capsys) -> None:  # type: ignore[no-untyped-def]
    assert capture.main(["--list", "--only", "feature-2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert all("pending" not in line for line in lines)
