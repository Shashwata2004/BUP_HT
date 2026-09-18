from copy import deepcopy

import pytest

from app.errors import GuardrailError
from app.guardrails import parse_json, validate_directives
from tests.conftest import make_directive

VALID = [
    ("no_op", None),
    ("solar_reduction", {"hours": [2, 3], "factor": 0.3}),
    ("minimum_battery_reserve", {"hours": [2, 3], "minimum_energy_kwh": 12}),
    ("no_charge_window", {"hours": [2, 3]}),
    ("no_discharge_window", {"hours": [2, 3]}),
    ("max_grid_window", {"hours": [2, 3], "max_grid_kwh": 42}),
]


@pytest.mark.parametrize("kind,adjustment", VALID)
def test_every_type(scenario, kind, adjustment):
    scenario.operator_notes = ["test"]
    result = validate_directives(
        {"directive_interpretation": [make_directive(kind, adjustment)]}, scenario
    )
    assert result[0].directive_type == kind


@pytest.mark.parametrize(
    "field,value",
    [
        ("note_index", -1),
        ("note_index", 1),
        ("note_index", True),
        ("note_index", 0.0),
        ("applies", False),
        ("applies", "true"),
        ("applies", 1),
        ("directive_type", "change_tariff"),
        ("structured_adjustment", None),
        ("explanation", 123),
        ("extra", "forbidden"),
    ],
)
def test_invalid_directive_fields(scenario, field, value):
    scenario.operator_notes = ["test"]
    d = make_directive("solar_reduction", {"hours": [1], "factor": 0.5})
    d[field] = value
    with pytest.raises(GuardrailError):
        validate_directives({"directive_interpretation": [d]}, scenario)


@pytest.mark.parametrize("hours", [[2, 1], [1, 1], [-1], [24], [True], [1.0], ["1"], [], None])
def test_bad_hours(scenario, hours):
    scenario.operator_notes = ["test"]
    with pytest.raises(GuardrailError):
        validate_directives(
            {"directive_interpretation": [make_directive("no_charge_window", {"hours": hours})]},
            scenario,
        )


@pytest.mark.parametrize(
    "kind,key,value",
    [
        ("solar_reduction", "factor", -0.1),
        ("solar_reduction", "factor", 1.1),
        ("solar_reduction", "factor", float("nan")),
        ("solar_reduction", "factor", True),
        ("solar_reduction", "factor", "0.2"),
        ("max_grid_window", "max_grid_kwh", -1),
        ("max_grid_window", "max_grid_kwh", float("inf")),
        ("minimum_battery_reserve", "minimum_energy_kwh", -1),
        ("minimum_battery_reserve", "minimum_energy_kwh", 1e6),
        ("minimum_battery_reserve", "minimum_energy_kwh", float("inf")),
    ],
)
def test_numeric_bounds(scenario, kind, key, value):
    scenario.operator_notes = ["test"]
    with pytest.raises(GuardrailError):
        validate_directives(
            {"directive_interpretation": [make_directive(kind, {"hours": [1], key: value})]},
            scenario,
        )


@pytest.mark.parametrize("kind,adjustment", VALID)
def test_applies_and_extra_keys(scenario, kind, adjustment):
    scenario.operator_notes = ["test"]
    d = make_directive(kind, deepcopy(adjustment))
    d["applies"] = not d["applies"]
    with pytest.raises(GuardrailError):
        validate_directives({"directive_interpretation": [d]}, scenario)
    if adjustment is not None:
        d = make_directive(kind, {**adjustment, "demand_kwh": 0})
        with pytest.raises(GuardrailError):
            validate_directives({"directive_interpretation": [d]}, scenario)


@pytest.mark.parametrize("indices", [[], [0], [0, 0], [1, 0], [0, 2], [0, 1, 2]])
def test_note_mapping(scenario, indices):
    with pytest.raises(GuardrailError):
        validate_directives(
            {"directive_interpretation": [make_directive(index=i) for i in indices]}, scenario
        )


@pytest.mark.parametrize(
    "raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', "```json\n{}\n```", "{", "not json"]
)
def test_json_rejection(raw):
    with pytest.raises(GuardrailError):
        parse_json(raw)


def test_noop_must_be_null(scenario):
    scenario.operator_notes = ["test"]
    with pytest.raises(GuardrailError):
        validate_directives({"directive_interpretation": [make_directive(adjustment={})]}, scenario)
