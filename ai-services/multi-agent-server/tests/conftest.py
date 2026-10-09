"""Shared fixtures: a domain-neutral template, fixture tools and an in-process service."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from agent_core import LLMProvider
from multi_agent_server.agents import AgentSettings, StructuredCaller
from multi_agent_server.app import create_app
from multi_agent_server.execution import InlineExecutor, StageExecutor
from multi_agent_server.prompts import PromptRegistry
from multi_agent_server.providers import DeterministicProvider
from multi_agent_server.service import WorkflowService
from multi_agent_server.settings import MultiAgentSettings
from multi_agent_server.store import WorkflowStore
from multi_agent_server.templates import TemplateRegistry
from multi_agent_server.tools import FixtureToolGateway, ToolGateway

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE_PATH = FIXTURES / "workflow.yaml"
TOOLS_PATH = FIXTURES / "tools.json"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
TOKEN = "test-multi-agent-token-0123456789abcdef"
TEMPLATE_ID = "example-readiness-review"


class DeferredExecutor:
    """Collects tasks so a test can observe intermediate states, then run them."""

    def __init__(self) -> None:
        self.tasks: list[object] = []
        self.capacity = True

    def has_capacity(self) -> bool:
        return self.capacity

    def submit(self, task: object) -> None:
        self.tasks.append(task)

    def run_all(self) -> None:
        while self.tasks:
            task = self.tasks.pop(0)
            assert callable(task)
            task()

    def shutdown(self) -> None:
        self.tasks.clear()


def make_service(
    state_directory: Path,
    *,
    gateway: ToolGateway | None = None,
    provider: LLMProvider | None = None,
    mode: str = "deterministic",
    executor: StageExecutor | None = None,
    agent_settings: AgentSettings | None = None,
    registry: TemplateRegistry | None = None,
) -> WorkflowService:
    """An in-process service over the fixture template and tools."""
    caller = StructuredCaller(
        provider or DeterministicProvider(),
        mode="model" if mode == "model" else "deterministic",
        model_profile="test-profile" if mode == "model" else "deterministic",
        settings=agent_settings or AgentSettings(),
        prompts=PromptRegistry(),
    )
    return WorkflowService(
        registry=registry or TemplateRegistry.from_paths([TEMPLATE_PATH]),
        store=WorkflowStore(state_directory),
        gateway=gateway or FixtureToolGateway.from_file(TOOLS_PATH),
        caller=caller,
        executor=executor or InlineExecutor(),
    )


@pytest.fixture
def service(tmp_path: Path) -> Iterator[WorkflowService]:
    workflows = make_service(tmp_path / "state")
    yield workflows
    workflows.close()


@pytest.fixture
def app(service: WorkflowService) -> Flask:
    return create_app(MultiAgentSettings(token=TOKEN), service=service)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {TOKEN}"
    return test_client


@pytest.fixture
def service_factory(tmp_path: Path) -> Iterator[object]:
    """Build extra services in this test's temporary directory; all are closed afterwards."""
    created: list[WorkflowService] = []

    def factory(name: str = "state", **options: object) -> WorkflowService:
        workflows = make_service(tmp_path / name, **options)  # type: ignore[arg-type]
        created.append(workflows)
        return workflows

    yield factory
    for workflows in created:
        workflows.close()


@pytest.fixture
def deferred() -> DeferredExecutor:
    return DeferredExecutor()
