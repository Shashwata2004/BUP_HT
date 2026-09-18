"""Seeded feasible witnesses, independent optimality, and decimal interactions."""

import itertools
import math
import random

import pytest

from app.models import OptimizationResponse, Scenario
from app.validator import validate_plan
from tests.conftest import make_directive
from tests.test_optimizer import exhaustive_cost, solve, synthetic_scenario


def feasible_case(seed: int) -> tuple[dict, list[dict], dict]:
    rng = random.Random(20260918 + seed)
    scale = [0.1, 0.2, 12.34, 99.99, 1000, 1000000][seed % 6]
    capacity = scale * rng.uniform(0.5, 2)
    minimum = capacity * rng.choice([0, 0.1, 0.5, 1])
    initial = rng.choice([minimum, capacity, (minimum + capacity) / 2])
    charge = scale * rng.choice([0, 0.01, 0.2, 1])
    discharge = scale * rng.choice([0, 0.03, 0.3, 1])
    # A reversible walk proves feasibility, including neutrality, before invoking the LP.
    energy, flows = initial, []
    rate = min(charge, discharge)
    for _ in range(12):
        flow = rng.uniform(-min(rate, energy - minimum), min(rate, capacity - energy))
        flows.append(flow)
        energy += flow
    flows += [-flow for flow in reversed(flows)]
    states, energy = [], initial
    for flow in flows:
        energy += flow
        states.append(energy)
    raw = []
    solar = [scale * rng.choice([0, 0.01, 0.5, 10]) for _ in range(24)]
    effective = solar.copy()
    kinds = rng.sample(
        [
            "solar_reduction",
            "minimum_battery_reserve",
            "no_charge_window",
            "no_discharge_window",
            "max_grid_window",
            "no_op",
        ],
        1 + seed % 3,
    )
    for index, kind in enumerate(kinds):
        eligible = list(range(24))
        if kind == "no_charge_window":
            eligible = [h for h in eligible if flows[h] <= 0]
        if kind == "no_discharge_window":
            eligible = [h for h in eligible if flows[h] >= 0]
        hours = sorted(rng.sample(eligible, min(len(eligible), rng.randint(1, 12))))
        adjustment = {"hours": hours}
        if kind == "solar_reduction":
            adjustment["factor"] = rng.choice([0, 0.125, 1 / 3, 0.7, 1])
            for h in hours:
                effective[h] *= adjustment["factor"]
        if kind == "minimum_battery_reserve":
            adjustment["minimum_energy_kwh"] = max(0, min(capacity, min(states[h] for h in hours)))
        if kind == "max_grid_window":
            adjustment["max_grid_kwh"] = 0  # filled from the feasible witness below
        raw.append(make_directive(kind, None if kind == "no_op" else adjustment, index))
    data = synthetic_scenario()
    data.update(scenario_id=f"seed-{seed}", operator_notes=["Synthetic fixture"] * len(raw))
    data["battery"] = dict(
        capacity_kwh=capacity,
        initial_energy_kwh=initial,
        minimum_energy_kwh=minimum,
        max_charge_kwh_per_hour=charge,
        max_discharge_kwh_per_hour=discharge,
    )
    plan = []
    for h, flow in enumerate(flows):
        supply = scale * rng.choice([0, 0.001, 0.1, 2]) + max(0, flow)
        used = min(supply, effective[h])
        grid = supply - used
        tariff = rng.choice([0, 0.1, 0.2, 12.34, 99.99]) if seed % 7 else 0.2
        data["hours"][h].update(
            demand_kwh=supply - flow, solar_kwh=solar[h], tariff_bdt_per_kwh=tariff
        )
        plan.append(
            dict(
                hour=h,
                grid_kwh=grid,
                solar_used_kwh=used,
                battery_action="charge" if flow > 0 else "discharge" if flow < 0 else "idle",
                battery_kwh=abs(flow),
                battery_energy_after_kwh=max(0, states[h]),
            )
        )
    for directive in raw:
        if directive["directive_type"] == "max_grid_window":
            a = directive["structured_adjustment"]
            a["max_grid_kwh"] = max(plan[h]["grid_kwh"] for h in a["hours"])
    witness = dict(
        scenario_id=data["scenario_id"],
        directive_interpretation=raw,
        hourly_plan=plan,
        total_grid_kwh=math.fsum(p["grid_kwh"] for p in plan),
        total_cost_bdt=math.fsum(
            p["grid_kwh"] * data["hours"][p["hour"]]["tariff_bdt_per_kwh"] for p in plan
        ),
        peak_grid_kwh=max(p["grid_kwh"] for p in plan),
        plan_summary="Feasible witness",
    )
    return data, raw, witness


@pytest.mark.parametrize("seed", range(1000))
def test_seeded_feasible_scenario(seed):
    data, raw, witness = feasible_case(seed)
    scenario = Scenario.model_validate(data)
    validate_plan(scenario, OptimizationResponse.model_validate(witness))
    _, result = solve(data, raw)
    validate_plan(scenario, result)
    assert result.total_cost_bdt <= witness["total_cost_bdt"] + 0.01
    assert math.isclose(
        result.total_grid_kwh, math.fsum(p.grid_kwh for p in result.hourly_plan), abs_tol=1e-6
    )


KINDS = [
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


@pytest.mark.parametrize(
    "kinds", list(itertools.combinations(KINDS, 2)) + list(itertools.combinations(KINDS, 3))
)
def test_all_different_type_interactions_against_integer_oracle(kinds):
    data = synthetic_scenario()
    data["operator_notes"] *= len(kinds)
    for h in data["hours"]:
        h["solar_kwh"] = 4
    adjustments = {
        "solar_reduction": {"hours": [12, 13], "factor": 0.5},
        "minimum_battery_reserve": {"hours": [12, 13], "minimum_energy_kwh": 2},
        "no_charge_window": {"hours": [12, 13]},
        "no_discharge_window": {"hours": [12, 13]},
        "max_grid_window": {"hours": [12, 13], "max_grid_kwh": 2},
        "no_op": None,
    }
    raw = [make_directive(k, adjustments[k], i) for i, k in enumerate(kinds)]
    _, result = solve(data, raw)
    assert result.total_cost_bdt == pytest.approx(exhaustive_cost(data, raw), abs=1e-7)


@pytest.mark.parametrize(
    "kind",
    [
        "early_cheap",
        "late_cheap",
        "flat",
        "full",
        "reserve",
        "rate",
        "surplus",
        "cap",
        "expensive_reserve",
        "zero_rates",
    ],
)
def test_named_optimality_oracles(kind):
    data, raw = synthetic_scenario(), [make_directive()]
    if kind == "late_cheap":
        for h in data["hours"]:
            h["tariff_bdt_per_kwh"] = 4 - h["tariff_bdt_per_kwh"]
    if kind == "flat":
        for h in data["hours"]:
            h["tariff_bdt_per_kwh"] = 2
    if kind in {"full", "reserve"}:
        data["battery"]["initial_energy_kwh"] = 4 if kind == "full" else 0
    if kind in {"rate", "zero_rates"}:
        data["battery"].update(
            max_charge_kwh_per_hour=1 if kind == "rate" else 0,
            max_discharge_kwh_per_hour=1 if kind == "rate" else 0,
        )
    if kind == "surplus":
        for h in data["hours"][6:12]:
            h["solar_kwh"] = 9
    if kind == "cap":
        raw = [make_directive("max_grid_window", {"hours": [12, 13], "max_grid_kwh": 3})]
    if kind == "expensive_reserve":
        raw = [
            make_directive("minimum_battery_reserve", {"hours": [12, 13], "minimum_energy_kwh": 4})
        ]
    _, result = solve(data, raw)
    assert result.total_cost_bdt == pytest.approx(exhaustive_cost(data, raw), abs=1e-7)


@pytest.mark.parametrize("unit", [0.1, 0.2, 12.34, 99.99])
@pytest.mark.parametrize("initial", [0, 2, 4])
@pytest.mark.parametrize("rate", [0, 1])
def test_decimal_optimality_by_exact_unit_conversion(unit, initial, rate):
    data = synthetic_scenario()
    data["battery"].update(
        initial_energy_kwh=initial, max_charge_kwh_per_hour=rate, max_discharge_kwh_per_hour=rate
    )
    raw = [make_directive("max_grid_window", {"hours": [12, 13], "max_grid_kwh": 4})]
    expected = exhaustive_cost(data, raw) * unit
    for key in data["battery"]:
        data["battery"][key] *= unit
    for h in data["hours"]:
        h["demand_kwh"] *= unit
        h["solar_kwh"] *= unit
    raw[0]["structured_adjustment"]["max_grid_kwh"] *= unit
    _, result = solve(data, raw)
    assert result.total_cost_bdt == pytest.approx(expected, rel=0, abs=1e-6)
