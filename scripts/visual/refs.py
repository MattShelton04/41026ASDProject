"""Choose the two commits a visual capture compares, and write them to ``GITHUB_OUTPUT``.

    python3 -m scripts.visual.refs <git checkout>

Pull requests compare the merge base with the exact head, so every push re-compares the whole pull
request and changes made independently on main never appear as pull request changes. Pushes to
main compare the previous tip with the new one. Uses only the standard library.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from scripts.visual.policy import SHA

Git = Callable[[Sequence[str]], str]


def comparison_refs(
    event: Mapping[str, Any], event_name: str, sha: str, git: Git
) -> tuple[str, str]:
    """Return ``(base, head)`` commit SHAs for a workflow event."""
    pull_request = event.get("pull_request") or {}
    head = str((pull_request.get("head") or {}).get("sha") or sha)
    base = str((pull_request.get("base") or {}).get("sha") or event.get("before") or "")
    if not SHA.fullmatch(head):
        raise ValueError("invalid head SHA")
    if event_name == "pull_request":
        if not SHA.fullmatch(base):
            raise ValueError("invalid base SHA")
        # The event's base SHA can predate main commits merged into the PR. The generated merge
        # commit's first parent is the base tip GitHub merged against; use it when its second
        # parent is this exact head.
        parents = git(["rev-list", "--parents", "-n", "1", sha]).split()[1:]
        if len(parents) == 2 and parents[1] == head and SHA.fullmatch(parents[0]):
            base = parents[0]
        base = git(["merge-base", base, head])
    elif not base or set(base) == {"0"}:
        # Manual runs and a branch's first push compare against the first parent.
        base = git(["rev-parse", f"{head}^"])
    if not SHA.fullmatch(base) or base == head:
        raise ValueError("a comparison needs two distinct commits")
    return base, head


def main(argv: Sequence[str]) -> int:
    """Compute refs for the current GitHub Actions event."""
    checkout = argv[0] if argv else "."

    def git(arguments: Sequence[str]) -> str:
        return subprocess.run(
            ("git", "-C", checkout, *arguments), check=True, capture_output=True, text=True
        ).stdout.strip()

    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
        event = json.load(handle)
    base, head = comparison_refs(
        event, os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_SHA"], git
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"base={base}\nhead={head}\n")
    print(f"Comparison: {base} -> {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
