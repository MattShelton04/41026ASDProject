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
from ai_mode.adapters.ollama import OllamaProvider
from ai_mode.configuration import Settings
from ai_mode.providers import PRIMARY_MODEL_PROFILE, build_ollama_provider


class SmokeItem(BaseModel):
    """Nested dynamic data representative of production plan schemas."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    arguments: dict[str, JsonValue]


class SmokeResponse(BaseModel):
    """Schema proving structured output and complex-grammar compatibility."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    message: str
    items: tuple[SmokeItem, ...] = Field(min_length=1, max_length=50)


def run_smoke(provider: LLMProvider) -> Mapping[str, object]:
    """Exercise health and one schema-constrained turn through the provider port."""
    health = provider.health()
    if not health.reachable:
        raise RuntimeError(health.detail)
    request = StructuredModelRequest(
        run_id=uuid4(),
        role=ModelRole.REVIEWER,
        model_profile=PRIMARY_MODEL_PROFILE,
        messages=(
            ModelMessage(
                role="system",
                content="Return only the requested JSON object. Do not add extra fields.",
            ),
            ModelMessage(
                role="user",
                content=(
                    'Set ready to true, message to exactly "ollama-ready", and items to one '
                    "entry with sequence 1 and an empty arguments object."
                ),
            ),
        ),
        output_schema=SmokeResponse.model_json_schema(),
        prompt_id="ollama-smoke",
        prompt_version="v1",
        prompt_hash="0" * 64,
        rendered_input_hash="0" * 64,
        temperature=0,
        max_output_tokens=64,
    )
    generated = provider.generate_structured(request)
    response = SmokeResponse.model_validate(generated.content)
    if (
        response.ready is not True
        or response.message != "ollama-ready"
        or len(response.items) != 1
        or response.items[0].sequence != 1
        or response.items[0].arguments != {}
    ):
        raise RuntimeError("Ollama returned valid but unexpected diagnostic content")
    return {
        "status": "ready",
        "provider": generated.provider,
        "model": generated.model,
        "content": response.model_dump(mode="json"),
        "metrics": generated.metrics.model_dump(mode="json"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override OLLAMA_BASE_URL for this check",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override OLLAMA_MODEL for this check",
    )
    parser.add_argument("--timeout-seconds", type=float, default=None)
    return parser


def main() -> int:
    """Run the diagnostic and emit a bounded machine-readable report."""
    args = _parser().parse_args()
    provider: OllamaProvider | None = None
    try:
        environment = dict(os.environ)
        if args.base_url is not None:
            environment["OLLAMA_BASE_URL"] = args.base_url
        if args.model is not None:
            environment["OLLAMA_MODEL"] = args.model
        if args.timeout_seconds is not None:
            environment["OLLAMA_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
        provider = build_ollama_provider(Settings.from_env(environment))
        print(json.dumps(run_smoke(provider), indent=2, sort_keys=True))
        return 0
    except (ModelProviderError, RuntimeError, ValueError) as exc:
        print(f"Ollama diagnostic failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if provider is not None:
            provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
