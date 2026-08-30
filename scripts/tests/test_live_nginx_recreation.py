"""Deterministic planner tests for the live Nginx recreation gate."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from scripts.live_nginx_recreation import validate_recreation


def test_recreation_requires_a_new_backend_and_recovers_same_edge() -> None:
    captures = iter(("old-container", "new-container"))
    health = iter((True, False, True))
    commands: list[tuple[str, ...]] = []

    before, after = validate_recreation(
        health_url="http://edge.test/health/ready",
        capture=lambda _command: next(captures),
        run=lambda command: commands.append(tuple(command)),
        ready=lambda _url: next(health),
        timeout_seconds=2,
    )

    assert (before, after) == ("old-container", "new-container")
    assert commands[0][-4:] == ("stack", "rebuild", "f1-backend", "--offline")


def test_recreation_rejects_an_unchanged_backend() -> None:
    def unchanged(_command: Sequence[str]) -> str:
        return "same-container"

    with pytest.raises(RuntimeError, match="not recreated"):
        validate_recreation(
            health_url="http://edge.test/health/ready",
            capture=unchanged,
            run=lambda _command: None,
            ready=lambda _url: True,
        )
