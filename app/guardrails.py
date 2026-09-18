import json
from typing import Any

from pydantic import ValidationError

from app.errors import GuardrailError
from app.models import Directive, Interpretation, Scenario


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GuardrailError("duplicate JSON object keys are forbidden")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise GuardrailError("all numbers must be finite JSON numbers")


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, GuardrailError):
            raise
        raise GuardrailError("response must be one valid JSON object") from None


def validate_directives(raw: object, scenario: Scenario) -> list[Directive]:
    try:
        parsed = Interpretation.model_validate(raw)
    except ValidationError as exc:
        # Never include rejected values, arbitrary keys, or provider output in feedback/logs.
        codes = sorted({error["type"] for error in exc.errors(include_input=False)})
        raise GuardrailError("invalid directive schema: " + ", ".join(codes)) from None
    directives = parsed.directive_interpretation
    if [d.note_index for d in directives] != list(range(len(scenario.operator_notes))):
        raise GuardrailError("exactly one directive per note in note_index order is required")
    for directive in directives:
        if directive.directive_type == "minimum_battery_reserve":
            if directive.structured_adjustment.minimum_energy_kwh > scenario.battery.capacity_kwh:
                raise GuardrailError("reserve must not exceed battery capacity")
    return directives
