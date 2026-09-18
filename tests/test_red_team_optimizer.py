"""Named optimizer edge cases supplement the large seeded property suite."""

from copy import deepcopy
from math import fsum, isclose

import pytest

from app.guardrails import validate_directives
from app.models import Scenario
from app.optimizer import optimize
from app.validator import validate_plan
from tests.conftest import make_directive
from tests.test_optimizer import exhaustive_cost


def _scenario() -> dict:
    return {
        "scenario_id": "red-team-optimizer",
        "operator_notes": ["Synthetic no-op."],
        "hours": [
            {
                "hour": hour,
                "demand_kwh": 10.0,
                "solar_kwh": 2.0,
                "tariff_bdt_per_kwh": 1.0 if hour < 12 else 10.0,
            }
            for hour in range(24)
        ],
        "battery": {
            "capacity_kwh": 20.0,
            "initial_energy_kwh": 10.0,
            "minimum_energy_kwh": 0.0,
            "max_charge_kwh_per_hour": 5.0,
            "max_discharge_kwh_per_hour": 5.0,
        },
    }


def _solve_and_replay(data: dict, raw: list[dict]):
    data["operator_notes"] = [f"Synthetic directive {index}." for index in range(len(raw))]
    scenario = Scenario.model_validate(data)
    directives = validate_directives({"directive_interpretation": raw}, scenario)
    response = optimize(scenario, directives)
    validate_plan(scenario, response)

    energy = scenario.battery.initial_energy_kwh
    grid_values = []
    cost_values = []
    for source, plan in zip(scenario.hours, response.hourly_plan, strict=True):
        charge = plan.battery_kwh if plan.battery_action == "charge" else 0.0
        discharge = plan.battery_kwh if plan.battery_action == "discharge" else 0.0
        assert plan.grid_kwh >= 0 and plan.solar_used_kwh >= 0 and plan.battery_kwh >= 0
        assert isclose(
            plan.grid_kwh + plan.solar_used_kwh + discharge,
            source.demand_kwh + charge,
            rel_tol=0,
            abs_tol=1e-6,
        )
        energy += charge - discharge
        assert isclose(energy, plan.battery_energy_after_kwh, rel_tol=0, abs_tol=1e-6)
        grid_values.append(plan.grid_kwh)
        cost_values.append(plan.grid_kwh * source.tariff_bdt_per_kwh)

    assert isclose(energy, scenario.battery.initial_energy_kwh, rel_tol=0, abs_tol=1e-6)
    assert isclose(fsum(grid_values), response.total_grid_kwh, rel_tol=0, abs_tol=1e-6)
    assert isclose(fsum(cost_values), response.total_cost_bdt, rel_tol=0, abs_tol=1e-6)
    assert isclose(max(grid_values), response.peak_grid_kwh, rel_tol=0, abs_tol=1e-6)
    return scenario, response


@pytest.mark.parametrize(
    "initial,minimum,capacity,charge_rate,discharge_rate",
    [
        (0.0, 0.0, 20.0, 5.0, 5.0),
        (20.0, 0.0, 20.0, 5.0, 5.0),
        (20.0, 20.0, 20.0, 5.0, 5.0),
        (0.1, 0.0, 0.1, 0.02, 0.02),
        (10.0, 0.0, 20.0, 0.0, 5.0),
        (10.0, 0.0, 20.0, 5.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 0.0),
    ],
)
def test_battery_state_and_rate_boundaries(
    initial, minimum, capacity, charge_rate, discharge_rate
):
    data = _scenario()
    data["battery"].update(
        capacity_kwh=capacity,
        initial_energy_kwh=initial,
        minimum_energy_kwh=minimum,
        max_charge_kwh_per_hour=charge_rate,
        max_discharge_kwh_per_hour=discharge_rate,
    )
    _, response = _solve_and_replay(data, [make_directive()])
    assert response.hourly_plan[-1].battery_energy_after_kwh == pytest.approx(initial, abs=1e-7)


@pytest.mark.parametrize(
    "kind",
    [
        "zero_solar",
        "solar_surplus",
        "flat_tariff",
        "huge_tariff_spread",
        "zero_tariff",
        "very_low_tariff",
    ],
)
def test_supply_and_tariff_extremes(kind):
    data = _scenario()
    for hour in data["hours"]:
        if kind == "zero_solar":
            hour["solar_kwh"] = 0.0
        elif kind == "solar_surplus":
            hour["solar_kwh"] = 1000.0
        elif kind == "flat_tariff":
            hour["tariff_bdt_per_kwh"] = 12.34
        elif kind == "huge_tariff_spread":
            hour["tariff_bdt_per_kwh"] = 0.0001 if hour["hour"] < 12 else 1_000_000.0
        elif kind == "zero_tariff":
            hour["tariff_bdt_per_kwh"] = 0.0
        elif kind == "very_low_tariff":
            hour["tariff_bdt_per_kwh"] = 0.0001 + hour["hour"] * 0.00001
    _, response = _solve_and_replay(data, [make_directive()])
    if kind in {"solar_surplus", "zero_tariff"}:
        assert response.total_cost_bdt == pytest.approx(0, abs=1e-8)


def _interaction_case(kind: str) -> tuple[dict, list[dict]]:
    data = _scenario()
    raw: list[dict]
    if kind == "reserve_at_capacity":
        data["battery"]["initial_energy_kwh"] = 20.0
        raw = [
            make_directive(
                "minimum_battery_reserve", {"hours": [10, 11], "minimum_energy_kwh": 20.0}
            )
        ]
    elif kind == "grid_exact_minimum":
        data["battery"].update(max_charge_kwh_per_hour=0.0, max_discharge_kwh_per_hour=0.0)
        for hour in data["hours"]:
            hour["solar_kwh"] = 3.0
        raw = [make_directive("max_grid_window", {"hours": [7], "max_grid_kwh": 7.0})]
    elif kind == "zero_grid_feasible":
        for hour in data["hours"]:
            hour["solar_kwh"] = 10.0
        raw = [make_directive("max_grid_window", {"hours": [12], "max_grid_kwh": 0.0})]
    elif kind == "no_charge_cheapest":
        raw = [make_directive("no_charge_window", {"hours": list(range(12))})]
    elif kind == "no_discharge_expensive":
        raw = [make_directive("no_discharge_window", {"hours": list(range(12, 24))})]
    elif kind == "reserve_during_peak":
        raw = [
            make_directive(
                "minimum_battery_reserve", {"hours": [12, 13, 14], "minimum_energy_kwh": 9.99}
            )
        ]
    elif kind == "solar_loss_and_no_charge":
        raw = [
            make_directive("solar_reduction", {"hours": [8, 9], "factor": 0.0}, 0),
            make_directive("no_charge_window", {"hours": [8, 9]}, 1),
        ]
    elif kind == "reserve_and_grid_cap":
        data["battery"]["initial_energy_kwh"] = 20.0
        raw = [
            make_directive(
                "minimum_battery_reserve", {"hours": [14, 15], "minimum_energy_kwh": 15.0}, 0
            ),
            make_directive("max_grid_window", {"hours": [14, 15], "max_grid_kwh": 8.0}, 1),
        ]
    elif kind == "charge_and_discharge_blocks":
        raw = [
            make_directive("no_charge_window", {"hours": [1, 2]}, 0),
            make_directive("no_discharge_window", {"hours": [2, 3]}, 1),
        ]
    else:  # pragma: no cover
        raise AssertionError(kind)
    return data, raw


@pytest.mark.parametrize(
    "kind",
    [
        "reserve_at_capacity",
        "grid_exact_minimum",
        "zero_grid_feasible",
        "no_charge_cheapest",
        "no_discharge_expensive",
        "reserve_during_peak",
        "solar_loss_and_no_charge",
        "reserve_and_grid_cap",
        "charge_and_discharge_blocks",
    ],
)
def test_directive_boundaries_and_interactions(kind):
    data, raw = _interaction_case(kind)
    scenario, response = _solve_and_replay(data, raw)
    if kind == "grid_exact_minimum":
        assert response.hourly_plan[7].grid_kwh == pytest.approx(7.0, abs=1e-7)
    if kind == "zero_grid_feasible":
        assert response.hourly_plan[12].grid_kwh == pytest.approx(0, abs=1e-8)
    validate_plan(scenario, response)


@pytest.mark.parametrize("scale", [0.0001, 0.1, 0.2, 12.34, 99.99])
def test_decimal_and_near_tolerance_values(scale):
    data = _scenario()
    data["battery"].update(
        capacity_kwh=4 * scale,
        initial_energy_kwh=2 * scale,
        minimum_energy_kwh=0.1 * scale,
        max_charge_kwh_per_hour=scale,
        max_discharge_kwh_per_hour=scale,
    )
    for hour in data["hours"]:
        hour.update(
            demand_kwh=2 * scale + hour["hour"] * scale / 100,
            solar_kwh=scale + (hour["hour"] % 3) * scale / 10,
            tariff_bdt_per_kwh=0.01 + (hour["hour"] % 5) * 0.2,
        )
    _solve_and_replay(
        data,
        [
            make_directive(
                "solar_reduction", {"hours": [5, 6], "factor": 0.99}, 0
            ),
            make_directive(
                "minimum_battery_reserve",
                {"hours": [7, 8], "minimum_energy_kwh": 0.2 * scale},
                1,
            ),
            make_directive(
                "max_grid_window", {"hours": [9], "max_grid_kwh": 3 * scale}, 2
            ),
        ],
    )


def test_many_equivalent_flat_tariff_schedules_keep_optimal_cost():
    data = _scenario()
    for hour in data["hours"]:
        hour.update(solar_kwh=0, tariff_bdt_per_kwh=3)
    _, first = _solve_and_replay(deepcopy(data), [make_directive()])
    _, second = _solve_and_replay(deepcopy(data), [make_directive()])
    assert first.total_cost_bdt == pytest.approx(24 * 10 * 3)
    assert second.total_cost_bdt == pytest.approx(first.total_cost_bdt)


@pytest.mark.parametrize("kind", ["cheap_early", "expensive_early", "flat", "solar_surplus"])
def test_named_integral_cases_match_independent_dynamic_program(kind):
    data = _scenario()
    data["battery"].update(
        capacity_kwh=4,
        initial_energy_kwh=2,
        minimum_energy_kwh=0,
        max_charge_kwh_per_hour=2,
        max_discharge_kwh_per_hour=2,
    )
    for hour in data["hours"]:
        hour.update(demand_kwh=4, solar_kwh=0)
        if kind == "cheap_early":
            hour["tariff_bdt_per_kwh"] = 1 if hour["hour"] < 12 else 5
        elif kind == "expensive_early":
            hour["tariff_bdt_per_kwh"] = 5 if hour["hour"] < 12 else 1
        elif kind == "flat":
            hour["tariff_bdt_per_kwh"] = 3
        else:
            hour.update(solar_kwh=6 if 8 <= hour["hour"] < 16 else 0, tariff_bdt_per_kwh=3)
    raw = [make_directive()]
    _, response = _solve_and_replay(deepcopy(data), raw)
    assert response.total_cost_bdt == pytest.approx(exhaustive_cost(data, raw), abs=1e-7)
