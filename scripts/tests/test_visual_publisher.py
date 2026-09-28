"""The trusted visual publisher: comparison refs, artifact extraction, events and comments."""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from scripts.visual import comment, publish
from scripts.visual.extract import extract
from scripts.visual.refs import comparison_refs

BASE, MAIN_TIP, HEAD, MERGE = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)


def _git(responses: dict[tuple[str, ...], str]) -> Any:
    def git(arguments: Sequence[str]) -> str:
        return responses[tuple(arguments)]

    return git


def test_pull_requests_compare_the_merge_base_of_the_merged_main_tip() -> None:
    git = _git(
        {
            ("rev-list", "--parents", "-n", "1", MERGE): f"{MERGE} {MAIN_TIP} {HEAD}",
            ("merge-base", MAIN_TIP, HEAD): BASE,
        }
    )
    event = {"pull_request": {"head": {"sha": HEAD}, "base": {"sha": "9" * 40}}}
    assert comparison_refs(event, "pull_request", MERGE, git) == (BASE, HEAD)


def test_pushes_compare_the_previous_tip_and_first_pushes_use_the_parent() -> None:
    assert comparison_refs({"before": BASE}, "push", HEAD, _git({})) == (BASE, HEAD)
    git = _git({("rev-parse", f"{HEAD}^"): BASE})
    assert comparison_refs({"before": "0" * 40}, "push", HEAD, git) == (BASE, HEAD)
    assert comparison_refs({}, "workflow_dispatch", HEAD, git) == (BASE, HEAD)


def test_refs_reject_identical_or_malformed_commits() -> None:
    with pytest.raises(ValueError):
        comparison_refs({"before": HEAD}, "push", HEAD, _git({}))
    with pytest.raises(ValueError):
        comparison_refs({"before": BASE}, "push", "HEAD; rm -rf /", _git({}))


def _archive(path: Path, members: dict[str, bytes], *, symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return path


def test_extract_accepts_only_flat_capture_files(tmp_path: Path) -> None:
    archive = _archive(
        tmp_path / "a.zip",
        {"capture-fixture.json": b"{}", "shared-home.png": b"png", "shared-home.failed.png": b"x"},
    )
    written = extract(archive, tmp_path / "out")
    assert sorted(written) == ["capture-fixture.json", "shared-home.png"]
    assert not (tmp_path / "out" / "shared-home.failed.png").exists()


@pytest.mark.parametrize(
    "members",
    [
        {"../escape.png": b"x"},
        {"nested/shared-home.png": b"x"},
        {"index.html": b"<script>"},
        {"capture-other.json": b"{}"},
        {"Shared-Home.png": b"x"},
    ],
)
def test_extract_rejects_unexpected_names(tmp_path: Path, members: dict[str, bytes]) -> None:
    with pytest.raises(ValueError, match="unexpected"):
        extract(_archive(tmp_path / "a.zip", members), tmp_path / "out")


def test_extract_rejects_symlinks_and_oversized_members(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="symlink"):
        extract(_archive(tmp_path / "a.zip", {}, symlink="shared-home.png"), tmp_path / "out")
    large = _archive(tmp_path / "b.zip", {"capture-stack.json": b" " * 400_001})
    with pytest.raises(ValueError, match="size limit"):
        extract(large, tmp_path / "out")


def _run(**overrides: Any) -> dict[str, Any]:
    return {
        "workflow_run": {
            "id": 99,
            "run_attempt": 1,
            "path": publish.CAPTURE_WORKFLOW,
            "conclusion": "success",
            "head_sha": HEAD,
            "event": "pull_request",
            "repository": {"full_name": "owner/repo"},
            **overrides,
        }
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"path": ".github/workflows/other.yml"},
        {"repository": {"full_name": "someone/else"}},
        {"conclusion": "cancelled"},
        {"head_sha": "not-a-sha"},
        {"id": "99"},
    ],
)
def test_publisher_ignores_unexpected_events(overrides: dict[str, Any]) -> None:
    with pytest.raises(publish.SkipPublicationError):
        publish.validate_event(_run(**overrides), "owner/repo")


def test_publisher_accepts_failed_capture_runs_so_limitations_are_reported() -> None:
    run = publish.validate_event(_run(conclusion="failure"), "owner/repo")
    assert run["id"] == 99


class FakeGitHub:
    """Records REST calls and answers from a routing table."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, Any]] = []

    def request(self, path: str, *, method: str = "GET", body: object = None) -> Any:
        self.calls.append((method, path, body))
        return self.routes.get((method, path.split("?")[0]))


def test_fork_pull_requests_are_found_by_head_label_and_exact_head() -> None:
    github = FakeGitHub(
        {
            ("GET", "/pulls"): [{"number": 5}, {"number": 6}],
            ("GET", "/pulls/5"): {"state": "open", "head": {"sha": "f" * 40}, "title": "stale"},
            ("GET", "/pulls/6"): {"state": "open", "head": {"sha": HEAD}, "title": "Fork change"},
        }
    )
    run = _run(head_repository={"owner": {"login": "fork"}}, head_branch="topic")
    found = publish.find_pull_request(github, run["workflow_run"])  # type: ignore[arg-type]
    assert found == {"number": 6, "title": "Fork change"}
    assert ("GET", "/pulls?state=open&per_page=30&head=fork:topic", None) in github.calls


def test_push_runs_are_not_associated_with_pull_requests() -> None:
    run = _run(event="push")["workflow_run"]
    assert publish.find_pull_request(FakeGitHub({}), run) is None  # type: ignore[arg-type]


def test_sticky_comment_is_created_then_edited_in_place() -> None:
    github = FakeGitHub({("GET", "/issues/7/comments"): []})
    body = f"{comment.MARKER}\nreport"
    assert publish.post_comment(github, 7, body, run_id=10, attempt=1) == "created"  # type: ignore[arg-type]
    posted = github.calls[-1]
    assert posted[0] == "POST"
    existing = {
        "id": 55,
        "user": {"login": publish.BOT_LOGIN},
        "body": comment.stamp(body, 10, 1),
    }
    github = FakeGitHub({("GET", "/issues/7/comments"): [existing]})
    assert publish.post_comment(github, 7, body, run_id=11, attempt=1) == "updated"  # type: ignore[arg-type]
    assert github.calls[-1][:2] == ("PATCH", "/issues/comments/55")
    github = FakeGitHub({("GET", "/issues/7/comments"): [existing]})
    result = publish.post_comment(github, 7, body, run_id=9, attempt=1)  # type: ignore[arg-type]
    assert result.startswith("skipped")
    assert all(method == "GET" for method, _, _ in github.calls)


def test_comments_by_other_users_are_never_edited() -> None:
    impostor = {"id": 1, "user": {"login": "someone"}, "body": comment.MARKER}
    github = FakeGitHub({("GET", "/issues/7/comments"): [impostor]})
    assert publish.post_comment(github, 7, comment.MARKER, run_id=1, attempt=1) == "created"  # type: ignore[arg-type]
