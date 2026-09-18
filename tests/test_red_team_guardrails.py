"""Deterministic mutation fuzzing for the untrusted model-output boundary."""

import json
import math
import random
from copy import deepcopy

import pytest

from app.errors import GuardrailError
from app.guardrails import parse_json, validate_directives
from tests.conftest import make_directive


def _invalid_payload(category: str, scenario, variation: int) -> dict:
    base = {
        "directive_interpretation": [
            make_directive(index=0),
            make_directive(index=1),
            make_directive(index=2),
        ]
    }
    directives = base["directive_interpretation"]
    scenario.operator_notes = ["first", "second", "third"]

    if category == "wrong_note_index":
        directives[0]["note_index"] = 3 + variation
    elif category == "missing_note_index":
        directives[0].pop("note_index")
    elif category == "duplicate_note_index":
        directives[1]["note_index"] = 0
    elif category == "missing_note":
        directives.pop()
    elif category == "extra_note":
        directives.append(make_directive(index=3))
    elif category == "wrong_applies_type":
        directives[0]["applies"] = variation % 2
    elif category == "noop_applies_true":
        directives[0]["applies"] = True
    elif category == "nonnull_noop_adjustment":
        directives[0]["structured_adjustment"] = {"hours": [variation % 24]}
    elif category == "nonnoop_applies_false":
        directives[0] = make_directive(
            "solar_reduction", {"hours": [1], "factor": 0.5}, 0
        )
        directives[0]["applies"] = False
    elif category == "missing_adjustment":
        directives[0] = make_directive(
            "solar_reduction", {"hours": [1], "factor": 0.5}, 0
        )
        directives[0].pop("structured_adjustment")
    elif category == "duplicate_hours":
        directives[0] = make_directive("no_charge_window", {"hours": [1, 1]}, 0)
    elif category == "unsorted_hours":
        directives[0] = make_directive("no_discharge_window", {"hours": [2, 1]}, 0)
    elif category == "negative_hour":
        directives[0] = make_directive("no_charge_window", {"hours": [-1 - variation]}, 0)
    elif category == "hour_24_or_more":
        directives[0] = make_directive("no_charge_window", {"hours": [24 + variation]}, 0)
    elif category == "string_hour":
        directives[0] = make_directive("no_charge_window", {"hours": [str(variation % 24)]}, 0)
    elif category == "empty_hours":
        directives[0] = make_directive("no_charge_window", {"hours": []}, 0)
    elif category == "nonfinite_factor":
        value = math.nan if variation % 2 else math.inf
        directives[0] = make_directive("solar_reduction", {"hours": [1], "factor": value}, 0)
    elif category == "negative_factor":
        directives[0] = make_directive(
            "solar_reduction", {"hours": [1], "factor": -0.001 * (variation + 1)}, 0
        )
    elif category == "factor_above_one":
        directives[0] = make_directive(
            "solar_reduction", {"hours": [1], "factor": 1.001 + variation}, 0
        )
    elif category == "reserve_above_capacity":
        directives[0] = make_directive(
            "minimum_battery_reserve",
            {"hours": [1], "minimum_energy_kwh": scenario.battery.capacity_kwh + variation + 1},
            0,
        )
    elif category == "negative_grid_cap":
        directives[0] = make_directive(
            "max_grid_window", {"hours": [1], "max_grid_kwh": -variation - 0.01}, 0
        )
    elif category == "null_required_number":
        directives[0] = make_directive(
            "max_grid_window", {"hours": [1], "max_grid_kwh": None}, 0
        )
    elif category == "numeric_string":
        directives[0] = make_directive(
            "minimum_battery_reserve", {"hours": [1], "minimum_energy_kwh": "12.5"}, 0
        )
    elif category == "wrong_adjustment_field":
        directives[0] = make_directive(
            "solar_reduction", {"hours": [1], "max_grid_kwh": variation + 1.0}, 0
        )
    elif category == "cross_type_field":
        directives[0] = make_directive(
            "no_discharge_window", {"hours": [1], "factor": 0.5}, 0
        )
    elif category == "extra_directive_field":
        directives[0]["unsupported_rule"] = variation
    elif category == "invalid_directive_enum":
        directives[0]["directive_type"] = f"demand_override_{variation}"
    elif category == "wrong_top_level_shape":
        return {"directive_interpretation": {"items": directives}}
    else:  # pragma: no cover - the category list below is exhaustive
        raise AssertionError(category)
    return base


def test_five_thousand_invalid_structured_mutations_never_reach_optimizer(scenario):
    categories = [
        "wrong_note_index",
        "missing_note_index",
        "duplicate_note_index",
        "missing_note",
        "extra_note",
        "wrong_applies_type",
        "noop_applies_true",
        "nonnull_noop_adjustment",
        "nonnoop_applies_false",
        "missing_adjustment",
        "duplicate_hours",
        "unsorted_hours",
        "negative_hour",
        "hour_24_or_more",
        "string_hour",
        "empty_hours",
        "nonfinite_factor",
        "negative_factor",
        "factor_above_one",
        "reserve_above_capacity",
        "negative_grid_cap",
        "null_required_number",
        "numeric_string",
        "wrong_adjustment_field",
        "cross_type_field",
        "extra_directive_field",
        "invalid_directive_enum",
        "wrong_top_level_shape",
    ]
    rng = random.Random(20260918)
    rejected = 0
    seen = set()
    for mutation_index in range(5000):
        category = categories[mutation_index % len(categories)]
        variation = rng.randrange(1, 1_000_000)
        payload = _invalid_payload(category, scenario, variation)
        with pytest.raises(GuardrailError):
            validate_directives(deepcopy(payload), scenario)
        rejected += 1
        seen.add(category)

    assert rejected == 5000
    assert seen == set(categories)


def test_one_thousand_malformed_or_truncated_provider_responses_are_rejected():
    rng = random.Random(20260919)
    rejected = 0
    for index in range(1000):
        valid = json.dumps(
            {
                "directive_interpretation": [],
                "nonce": rng.randrange(1_000_000_000),
                "index": index,
            }
        )
        malformed = valid[:-1] if index % 2 else valid + f" trailing-{index}"
        with pytest.raises(GuardrailError):
            parse_json(malformed)
        rejected += 1

    for malformed in (
        '{"x": 1, "x": 2}',
        '{"x": NaN}',
        '{"x": Infinity}',
        '{"x": -Infinity}',
    ):
        with pytest.raises(GuardrailError):
            parse_json(malformed)
        rejected += 1
    assert rejected == 1004
