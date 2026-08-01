"""Package-boundary smoke tests for agent-core."""

import agent_core


def test_agent_core_is_an_independent_importable_package() -> None:
    assert agent_core.__doc__ is not None
