"""Provider-level real-model diagnostic with no application or Compose orchestration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_core import (
    LLMProvider,
    ModelMessage,
    ModelProviderError,
    ModelRole,
    StructuredModelRequest,
)
from ai_mode.configuration import Settings
from ai_mode.providers import build_provider, configured_model_registry
from shared_contracts import ModelRegistry


class SmokeItem(BaseModel):
    """Nested dynamic data representative of production plan schemas."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    arguments: dict[str, JsonValue]


class SmokeResponse(BaseModel):
    """Schema proving structured-output and parser compatibility."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    message: str
    items: tuple[SmokeItem, ...] = Field(min_length=1, max_length=50)


def run_smoke(
    provider: LLMProvider,
    *,
    model_profile: str = "remote-standard.v1",
    model_role: ModelRole = ModelRole.PLANNER,
) -> Mapping[str, object]:
    """Exercise health and one schema-guided turn through the provider port."""
    health = provider.health()
    if not health.reachable:
        raise RuntimeError(health.detail)
    request = StructuredModelRequest(
        run_id=uuid4(),
        role=model_role,
        model_profile=model_profile,
        messages=(
            ModelMessage(
                role="system",
                content="Return only the requested JSON object. Do not add extra fields.",
            ),
            ModelMessage(
                role="user",
                content=(
                    'Set ready to true, message to exactly "provider-ready", and items to one '
                    "entry with sequence 1 and an empty arguments object."
                ),
            ),
        ),
        output_schema=SmokeResponse.model_json_schema(),
        prompt_id="provider-smoke",
        prompt_version="v1",
        prompt_hash="0" * 64,
        rendered_input_hash="0" * 64,
        temperature=0,
        max_output_tokens=128,
    )
    generated = provider.generate_structured(request)
    response = SmokeResponse.model_validate(generated.content)
    if (
        response.ready is not True
        or response.message != "provider-ready"
        or len(response.items) != 1
        or response.items[0].sequence != 1
        or response.items[0].arguments != {}
    ):
        raise RuntimeError("Provider returned valid but unexpected diagnostic content")
    return {
        "status": "ready",
        "provider": generated.provider,
        "model": generated.model,
        "content": response.model_dump(mode="json"),
        "metrics": generated.metrics.model_dump(mode="json"),
    }


def _diagnostic_role(registry: ModelRegistry, model_profile: str) -> ModelRole:
    """Select a declared role so diagnostics also exercise profile enforcement."""
    profile = registry.profile(model_profile)
    if profile is None:  # configured_model_registry already validates this lookup.
        raise ValueError(f"model profile is not registered: {model_profile}")
    return ModelRole(next(iter(profile.role_models)).value)


def configuration_report(
    settings: Settings,
    registry: ModelRegistry,
    model_profile: str,
) -> Mapping[str, object]:
    """Return a secret-safe, network-free deployment preflight report."""
    profile = registry.profile(model_profile)
    if profile is None:
        raise ValueError(f"model profile is not registered: {model_profile}")
    role_models: dict[str, str] = {}
    for role, model_key in profile.role_models.items():
        model = registry.model(model_key)
        if model is None:  # ModelRegistry validation already rejects this.
            raise ValueError(f"model profile references unknown model: {model_key}")
        role_models[role.value] = model.model_id
    return {
        "status": "configuration-valid",
        "provider": settings.llm_provider,
        "base_url": settings.openai_base_url,
        "credential_configured": settings.openai_api_key is not None,
        "profile": model_profile,
        "role_models": role_models,
        "context_tokens": profile.context_tokens,
        "maximum_output_tokens": profile.maximum_output_tokens,
        "prompt_cache_enabled": settings.openai_prompt_cache_enabled,
        "network_checked": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override OPENAI_BASE_URL for this check",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Override the registry's default logical profile for this check",
    )
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and model routing without making a network request",
    )
    return parser


def main() -> int:
    """Run the diagnostic and emit a bounded machine-readable report."""
    args = _parser().parse_args()
    provider: LLMProvider | None = None
    try:
        environment = dict(os.environ)
        if args.base_url is not None:
            environment["OPENAI_BASE_URL"] = args.base_url
        if args.profile is not None:
            environment["AI_MODE_DEFAULT_MODEL_PROFILE"] = args.profile
        if args.timeout_seconds is not None:
            environment["OPENAI_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
        settings = Settings.from_env(environment)
        registry, model_profile = configured_model_registry(settings)
        if args.dry_run:
            print(
                json.dumps(
                    configuration_report(settings, registry, model_profile),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        provider = build_provider(
            settings,
            registry=registry,
            readiness_profile=model_profile,
        )
        print(
            json.dumps(
                run_smoke(
                    provider,
                    model_profile=model_profile,
                    model_role=_diagnostic_role(registry, model_profile),
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (ModelProviderError, RuntimeError, ValueError) as exc:
        print(f"Provider diagnostic failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if provider is not None:
            close = getattr(provider, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    raise SystemExit(main())
