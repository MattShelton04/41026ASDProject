"""Bounded validation and repair for probabilistic model output."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from agent_core.errors import ModelOutputValidationError, ModelProviderError
from agent_core.ports import (
    LLMProvider,
    ModelMessage,
    StructuredModelRequest,
    StructuredModelResult,
)

INVALID_OUTPUT_CONTEXT_LIMIT = 20_000


@dataclass(frozen=True, slots=True)
class ValidatedModelOutput[StructuredOutputT: BaseModel]:
    """Validated output and the provider metadata that produced it."""

    value: StructuredOutputT
    invocation: StructuredModelResult
    repair_count: int
    provider_retry_count: int


def generate_validated[StructuredOutputT: BaseModel](
    provider: LLMProvider,
    request: StructuredModelRequest,
    output_type: type[StructuredOutputT],
    *,
    max_repairs: int,
    validate: Callable[[StructuredOutputT], None] | None = None,
) -> ValidatedModelOutput[StructuredOutputT]:
    """Generate structured output with bounded schema and domain-informed repairs."""
    if max_repairs not in {0, 1, 2}:
        raise ValueError("max_repairs must be 0, 1, or 2")

    current_request = request.evolve(output_schema=output_type.model_json_schema())
    provider_retry_count = 0
    for attempt in range(max_repairs + 1):
        while True:
            try:
                result = provider.generate_structured(current_request)
                break
            except ModelProviderError as exc:
                if exc.code != "model_response_incomplete" or provider_retry_count >= 1:
                    raise
                provider_retry_count += 1
                current_request = current_request.evolve(
                    messages=(
                        *current_request.messages,
                        ModelMessage(
                            role="user",
                            content=(
                                "The provider returned an incomplete response. Return the complete "
                                "JSON object now, within the supplied schema and output budget. Do "
                                "not add prose or omit required result fields."
                            ),
                        ),
                    ),
                )
        try:
            value = output_type.model_validate(result.content)
            if validate is not None:
                validate(value)
        except (ValidationError, ModelOutputValidationError) as exc:
            if attempt >= max_repairs:
                raise ModelOutputValidationError(
                    f"model output failed {output_type.__name__} validation"
                ) from exc
            invalid_output = json.dumps(
                result.content,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if len(invalid_output) > INVALID_OUTPUT_CONTEXT_LIMIT:
                invalid_output = (
                    invalid_output[:INVALID_OUTPUT_CONTEXT_LIMIT]
                    + "\n[previous response truncated]"
                )
            previous_response = ModelMessage(role="assistant", content=invalid_output)
            repair_instruction = ModelMessage(
                role="user",
                content=(
                    "The previous JSON response was invalid. Return only a corrected object that "
                    "matches the supplied schema and every registered tool contract. "
                    f"This is bounded repair {attempt + 1} of {max_repairs}. Validation errors: "
                    f"{_validation_feedback(exc)}"
                ),
            )
            current_request = current_request.evolve(
                messages=(
                    *current_request.messages,
                    previous_response,
                    repair_instruction,
                ),
                repair_attempt=attempt + 1,
            )
            continue
        return ValidatedModelOutput(
            value=value,
            invocation=result,
            repair_count=attempt,
            provider_retry_count=provider_retry_count,
        )

    raise AssertionError("bounded generation loop exited unexpectedly")


def _validation_feedback(exc: ValidationError | ModelOutputValidationError) -> object:
    if isinstance(exc, ValidationError):
        return exc.errors(include_url=False, include_input=False)
    return str(exc)
