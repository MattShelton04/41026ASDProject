"""Bounded validation and repair for probabilistic model output."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from agent_core.errors import ModelOutputValidationError
from agent_core.ports import (
    LLMProvider,
    ModelMessage,
    StructuredModelRequest,
    StructuredModelResult,
)


@dataclass(frozen=True, slots=True)
class ValidatedModelOutput[StructuredOutputT: BaseModel]:
    """Validated output and the provider metadata that produced it."""

    value: StructuredOutputT
    invocation: StructuredModelResult
    repair_count: int


def generate_validated[StructuredOutputT: BaseModel](
    provider: LLMProvider,
    request: StructuredModelRequest,
    output_type: type[StructuredOutputT],
    *,
    max_repairs: int,
) -> ValidatedModelOutput[StructuredOutputT]:
    """Generate structured output with at most the configured single repair."""
    if max_repairs not in {0, 1}:
        raise ValueError("max_repairs must be 0 or 1")

    current_request = request.model_copy(update={"output_schema": output_type.model_json_schema()})
    for attempt in range(max_repairs + 1):
        result = provider.generate_structured(current_request)
        try:
            value = output_type.model_validate(result.content)
        except ValidationError as exc:
            if attempt >= max_repairs:
                raise ModelOutputValidationError(
                    f"model output failed {output_type.__name__} validation"
                ) from exc
            repair_instruction = ModelMessage(
                role="user",
                content=(
                    "The previous JSON response was invalid. Return only a corrected object that "
                    "matches the supplied schema. Validation errors: "
                    f"{exc.errors(include_url=False)}"
                ),
            )
            current_request = current_request.model_copy(
                update={
                    "messages": (*current_request.messages, repair_instruction),
                    "repair_attempt": attempt + 1,
                }
            )
            continue
        return ValidatedModelOutput(value=value, invocation=result, repair_count=attempt)

    raise AssertionError("bounded generation loop exited unexpectedly")
