"""Trusted publisher: turn one completed Visual Capture run into a Pages gallery and PR comment.

    uv run --only-group visual python -m scripts.visual.publish --site <gh-pages> --work <dir>

Runs from the default branch in a ``workflow_run`` job. Capture artifacts come from untrusted pull
request code, so they are treated as data only: flat names, bounded sizes, validated PNGs, escaped
text. This process never executes anything from the pull request.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.visual import comment, pages
from scripts.visual.extract import extract
from scripts.visual.github import GitHub, valid_sha, wait_until_served
from scripts.visual.report import Report, build_report

CAPTURE_WORKFLOW = ".github/workflows/visual-capture.yml"
ARTIFACT = re.compile(r"^visual-(base|head)-(fixture|stack)$")
BOT_LOGIN = "github-actions[bot]"
PUSH_ATTEMPTS = 5
SQUASH_AFTER_COMMITS = 150


class SkipPublicationError(Exception):
    """This run should not be published; the message says why."""


def validate_event(event: Mapping[str, Any], repo: str) -> dict[str, Any]:
    """Return the capture run the event describes, or raise ``SkipPublicationError``."""
    run = event.get("workflow_run")
    if not isinstance(run, Mapping):
        raise SkipPublicationError("not a workflow_run event")
    if run.get("path") != CAPTURE_WORKFLOW:
        raise SkipPublicationError(f"unexpected source workflow {run.get('path')!r}")
    if (run.get("repository") or {}).get("full_name") != repo:
        raise SkipPublicationError("the capture run belongs to another repository")
    if run.get("conclusion") not in ("success", "failure"):
        raise SkipPublicationError(f"capture run concluded {run.get('conclusion')!r}")
    if not valid_sha(run.get("head_sha")):
        raise SkipPublicationError("the capture run has no valid head SHA")
    if not isinstance(run.get("id"), int) or not isinstance(run.get("run_attempt"), int):
        raise SkipPublicationError("the capture run has no valid ID")
    return dict(run)


def _artifacts(github: GitHub, run_id: int) -> dict[str, dict[str, Any]]:
    """Newest non-expired artifact per accepted name."""
    chosen: dict[str, dict[str, Any]] = {}
    for page in range(1, 4):
        listing = github.request(f"/actions/runs/{run_id}/artifacts?per_page=100&page={page}")
        items = listing.get("artifacts") or []
        for item in items:
            name = item.get("name")
            if not isinstance(name, str) or not ARTIFACT.fullmatch(name) or item.get("expired"):
                continue
            if name not in chosen or int(item["id"]) > int(chosen[name]["id"]):
                chosen[name] = item
        if len(items) < 100:
            break
    return chosen


def download(github: GitHub, run_id: int, work: Path) -> tuple[Path, Path, list[str]]:
    """Download and extract capture artifacts into ``work/base`` and ``work/head``."""
    base, head = work / "base", work / "head"
    base.mkdir(parents=True, exist_ok=True)
    head.mkdir(parents=True, exist_ok=True)
    found = []
    for name, item in sorted(_artifacts(github, run_id).items()):
        match = ARTIFACT.fullmatch(name)
        assert match is not None
        archive = work / f"{name}.zip"
        archive.write_bytes(github.download_artifact(int(item["id"])))
        extract(archive, base if match.group(1) == "base" else head)
        archive.unlink()
        found.append(name)
    return base, head, found


def find_pull_request(github: GitHub, run: Mapping[str, Any]) -> dict[str, Any] | None:
    """The open pull request whose current head is this run's head, if any."""
    if run.get("event") != "pull_request":
        return None
    head_sha = run["head_sha"]
    candidates = [item.get("number") for item in run.get("pull_requests") or []]
    owner = ((run.get("head_repository") or {}).get("owner") or {}).get("login")
    branch = run.get("head_branch")
    if not candidates and isinstance(owner, str) and isinstance(branch, str):
        # Fork pull requests are not listed on the run; find them by head label.
        for item in github.request(f"/pulls?state=open&per_page=30&head={owner}:{branch}") or []:
            candidates.append(item.get("number"))
    for number in candidates:
        if not isinstance(number, int):
            continue
        pull = github.request(f"/pulls/{number}")
        if pull.get("state") == "open" and (pull.get("head") or {}).get("sha") == head_sha:
            return {"number": number, "title": str(pull.get("title") or "")[:200]}
    return None


def _git(site: Path, *arguments: str, check: bool = True) -> str:
    return subprocess.run(
        ("git", "-C", str(site), *arguments), check=check, capture_output=True, text=True
    ).stdout.strip()


def push_pages(
    site: Path,
    *,
    report: Report,
    report_dir: Path,
    entry: Mapping[str, Any],
    title: str,
    repo: str,
) -> None:
    """Publish to ``gh-pages``, rebasing on concurrent publishers and squashing long histories."""
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        _git(site, "fetch", "--quiet", "origin", "gh-pages")
        _git(site, "reset", "--quiet", "--hard", "origin/gh-pages")
        _git(site, "clean", "-qfdx")
        remote = _git(site, "rev-parse", "HEAD")
        pages.publish_run(
            site, report=report, report_dir=report_dir, entry=entry, title=title, repo=repo
        )
        _git(site, "add", "--all")
        message = f"visual: publish run {entry['id']} ({str(entry['sha'])[:7]})"
        if int(_git(site, "rev-list", "--count", "HEAD")) >= SQUASH_AFTER_COMMITS:
            # Keep the branch small: one fresh root commit with the current, pruned tree.
            tree = _git(site, "write-tree")
            commit = _git(site, "commit-tree", tree, "-m", f"{message}; squash retained history")
            _git(site, "reset", "--quiet", "--hard", commit)
        else:
            _git(site, "commit", "--quiet", "--allow-empty", "-m", message)
        pushed = subprocess.run(
            (
                "git",
                "-C",
                str(site),
                "push",
                "--quiet",
                f"--force-with-lease=gh-pages:{remote}",
                "origin",
                "HEAD:gh-pages",
            ),
            capture_output=True,
            text=True,
        )
        if pushed.returncode == 0:
            return
        print(f"gh-pages push attempt {attempt} lost a race; retrying", file=sys.stderr)
        time.sleep(3 * attempt)
    raise RuntimeError("could not publish to gh-pages")


def post_comment(github: GitHub, number: int, body: str, run_id: int, attempt: int) -> str:
    """Create or update the one sticky visual comment on a pull request."""
    body = comment.stamp(body, run_id, attempt)
    existing = None
    for page in range(1, 11):
        items = github.request(f"/issues/{number}/comments?per_page=100&page={page}") or []
        for item in items:
            if (item.get("user") or {}).get("login") == BOT_LOGIN and comment.MARKER in (
                item.get("body") or ""
            ):
                existing = item
        if len(items) < 100:
            break
    if existing is None:
        github.request(f"/issues/{number}/comments", method="POST", body={"body": body})
        return "created"
    if comment.is_newer(existing.get("body") or "", run_id, attempt):
        return "skipped: a newer run already commented"
    github.request(f"/issues/comments/{existing['id']}", method="PATCH", body={"body": body})
    return "updated"


def step_summary(report: Report, gallery_url: str, pull: Mapping[str, Any] | None) -> str:
    """Markdown for the job summary."""
    counts = report.summary
    target = f"PR #{pull['number']}" if pull else "main"
    return (
        f"## Visual review for {target}\n\n"
        f"[Open the gallery]({gallery_url})\n\n"
        "| Changed | Subtle | Unchanged | Without baseline | Incomplete |\n"
        "|---:|---:|---:|---:|---:|\n"
        f"| {counts['changed']} | {counts['subtle']} | {counts['unchanged']} | "
        f"{counts['baseUnavailable']} | {counts['incomplete']} |\n"
    )


def publish(site: Path, work: Path, *, event: Mapping[str, Any], repo: str, token: str) -> int:
    """Publish one capture run; returns a process exit code."""
    try:
        run = validate_event(event, repo)
    except SkipPublicationError as reason:
        print(f"Nothing to publish: {reason}")
        return 0
    github = GitHub(repo, token)
    run_id, attempt, head_sha = int(run["id"]), int(run["run_attempt"]), str(run["head_sha"])
    latest = github.request(f"/actions/runs/{run_id}")
    if int(latest.get("run_attempt") or attempt) > attempt:
        print("A newer attempt of this capture run exists; it will publish instead.")
        return 0
    base_dir, head_dir, found = download(github, run_id, work)
    if not any(name.startswith("visual-head-") for name in found):
        print("The capture run uploaded no head screenshots; nothing to publish.")
        return 1
    pull = find_pull_request(github, run)
    title = f"PR #{pull['number']}: {pull['title']}" if pull else f"main @ {head_sha[:7]}"
    run_url = str(run.get("html_url") or f"https://github.com/{repo}/actions/runs/{run_id}")
    report_dir = work / "report"
    report = build_report(
        base_dir=base_dir,
        head_dir=head_dir,
        output=report_dir,
        title=title,
        metadata={"expectedHeadSha": head_sha, "runUrl": run_url},
    )
    entry = pages.run_entry(
        report,
        run_id=run_id,
        attempt=attempt,
        title=title,
        pr=pull["number"] if pull else None,
        pr_title=pull["title"] if pull else "",
    )
    push_pages(site, report=report, report_dir=report_dir, entry=entry, title=title, repo=repo)
    try:
        github.request("/pages/builds", method="POST")
    except urllib.error.HTTPError as exc:
        print(
            f"Pages build request returned {exc.code}; the push will still deploy.", file=sys.stderr
        )
    site_info = github.request("/pages")
    site_url = str(site_info.get("html_url") or "").rstrip("/") + f"/{pages.ROOT}/"
    gallery_url = f"{site_url}runs/{run_id}/"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(step_summary(report, gallery_url, pull))
    print(f"Published {gallery_url}")
    if pull is None:
        return 0
    if not wait_until_served(f"{gallery_url}changes.json"):
        print("Pages has not served the gallery yet; commenting anyway.", file=sys.stderr)
    body = comment.render(
        report.rows,
        report.summary,
        site=site_url,
        run_id=run_id,
        head_sha=head_sha,
        base_sha=report.metadata.get("baseSha"),
        attempt=attempt,
        run_url=run_url,
    )
    print(f"Pull request comment {post_comment(github, pull['number'], body, run_id, attempt)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the Visual Report workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site", type=Path, required=True, help="a git checkout of the gh-pages branch"
    )
    parser.add_argument(
        "--work", type=Path, help="scratch directory (default: a temporary directory)"
    )
    arguments = parser.parse_args(argv)
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
        event = json.load(handle)
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    if arguments.work:
        arguments.work.mkdir(parents=True, exist_ok=True)
        return publish(arguments.site, arguments.work, event=event, repo=repo, token=token)
    with tempfile.TemporaryDirectory() as work:
        return publish(arguments.site, Path(work), event=event, repo=repo, token=token)


if __name__ == "__main__":
    raise SystemExit(main())
