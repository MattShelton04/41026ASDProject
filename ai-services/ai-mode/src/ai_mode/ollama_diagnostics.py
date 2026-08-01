"""Provider-level real-model diagnostic with no application or Compose orchestration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from agent_core import (
    LLMProvider,
    ModelMessage,
    ModelProviderError,
    ModelRole,
    StructuredModelRequest,
)
from ai_mode.adapters.ollama import OllamaModelProfile, OllamaProvider

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:0.5b"


class SmokeResponse(BaseModel):
    """Minimal schema proving that the configured runtime honors structured output."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    message: str


def run_smoke(provider: LLMProvider) -> Mapping[str, object]:
    """Exercise health and one schema-constrained turn through the provider port."""
    health = provider.health()
    if not health.reachable:
        raise RuntimeError(health.detail)
    request = StructuredModelRequest(
        run_id=uuid4(),
        role=ModelRole.REVIEWER,
        model_profile="smoke.v1",
        messages=(
            ModelMessage(
                role="system",
                content="Return only the requested JSON object. Do not add extra fields.",
            ),
            ModelMessage(
                role="user",
                content='Set ready to true and message to exactly "ollama-ready".',
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
    if response.ready is not True or response.message != "ollama-ready":
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
        default=os.environ.get("OLLAMA_SMOKE_BASE_URL", DEFAULT_BASE_URL),
        help="Host-reachable Ollama URL",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL),
        help="Installed model tag to exercise",
    )
    parser.add_argument("--timeout-seconds", type=float, default=180)
    return parser


def main() -> int:
    """Run the diagnostic and emit a bounded machine-readable report."""
    args = _parser().parse_args()
    provider: OllamaProvider | None = None
    try:
        provider = OllamaProvider(
            base_url=args.base_url,
            profiles={"smoke.v1": OllamaModelProfile(model=args.model, keep_alive="30s")},
            timeout_seconds=args.timeout_seconds,
            max_response_bytes=100_000,
        )
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
