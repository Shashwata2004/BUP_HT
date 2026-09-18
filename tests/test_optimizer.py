import math
import random

import pytest

from app.errors import OptimizationError, ReplayError
from app.guardrails import validate_directives
from app.models import Scenario
from app.optimizer import optimize
from app.validator import validate_plan
from tests.conftest import make_directive


def synthetic_scenario() -> dict:
    return {
        "scenario_id": "synthetic",
        "operator_notes": ["synthetic"],
        "hours": [
            {"hour": h, "demand_kwh": 4, "solar_kwh": 0, "tariff_bdt_per_kwh": 1 if h < 12 else 3}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 4,
            "initial_energy_kwh": 2,
            "minimum_energy_kwh": 0,
            "max_charge_kwh_per_hour": 2,
            "max_discharge_kwh_per_hour": 2,
        },
    }


def solve(data, raw):
    scenario = Scenario.model_validate(data)
    directives = validate_directives({"directive_interpretation": raw}, scenario)
    return scenario, optimize(scenario, directives)


def test_arbitrage_and_neutrality():
    scenario, result = solve(synthetic_scenario(), [make_directive()])
    assert result.total_cost_bdt == pytest.approx(188)
    assert result.hourly_plan[-1].battery_energy_after_kwh == 2
    assert any(h.battery_action == "charge" for h in result.hourly_plan)
    assert any(h.battery_action == "discharge" for h in result.hourly_plan)
    validate_plan(scenario, result)


@pytest.mark.parametrize(
    "kind,adjustment",
    [
        ("no_charge_window", {"hours": list(range(24))}),
        ("no_discharge_window", {"hours": list(range(24))}),
        ("minimum_battery_reserve", {"hours": list(range(24)), "minimum_energy_kwh": 2}),
        ("solar_reduction", {"hours": list(range(24)), "factor": 0.4}),
        ("max_grid_window", {"hours": [12, 13], "max_grid_kwh": 3}),
    ],
)
def test_directive_changes_feasible_solution(kind, adjustment):
    data = synthetic_scenario()
    if kind == "solar_reduction":
        for h in data["hours"]:
            h["solar_kwh"] = 10
    scenario, result = solve(data, [make_directive(kind, adjustment)])
    validate_plan(scenario, result)
    if kind in {"no_charge_window", "no_discharge_window"}:
        assert all(h.battery_kwh == 0 for h in result.hourly_plan)
    if kind == "solar_reduction":
        assert result.total_cost_bdt == pytest.approx(0)


def test_multiple_simultaneous_directives():
    data = synthetic_scenario()
    data["operator_notes"] *= 3
    _, result = solve(
        data,
        [
            make_directive("no_charge_window", {"hours": [12, 13]}, 0),
            make_directive(
                "minimum_battery_reserve", {"hours": [12, 13], "minimum_energy_kwh": 2}, 1
            ),
            make_directive("max_grid_window", {"hours": [12, 13], "max_grid_kwh": 3}, 2),
        ],
    )
    assert result.hourly_plan[13].battery_energy_after_kwh >= 2
    assert all(result.hourly_plan[h].grid_kwh <= 3 for h in [12, 13])


def test_same_type_overlap():
    data = synthetic_scenario()
    data["operator_notes"] *= 2
    _, result = solve(
        data,
        [
            make_directive("max_grid_window", {"hours": [12], "max_grid_kwh": 4}),
            make_directive("max_grid_window", {"hours": [12], "max_grid_kwh": 2}, 1),
        ],
    )
    assert result.hourly_plan[12].grid_kwh <= 2


def test_no_charge_and_no_discharge_overlap():
    data = synthetic_scenario()
    data["operator_notes"] *= 2
    _, result = solve(
        data,
        [
            make_directive("no_charge_window", {"hours": list(range(24))}),
            make_directive("no_discharge_window", {"hours": list(range(24))}, 1),
        ],
    )
    assert all(h.battery_action == "idle" for h in result.hourly_plan)


def test_literal_solar_overlap_assignment():
    data = synthetic_scenario()
    data["operator_notes"] *= 2
    for h in data["hours"]:
        h["solar_kwh"] = 4
    _, result = solve(
        data,
        [
            make_directive("solar_reduction", {"hours": list(range(24)), "factor": 0.25}),
            make_directive("solar_reduction", {"hours": list(range(24)), "factor": 0.5}, 1),
        ],
    )
    assert sum(h.solar_used_kwh for h in result.hourly_plan) == pytest.approx(48)


@pytest.mark.parametrize("kind", ["zero_demand", "zero_capacity", "zero_tariff", "excess_solar"])
def test_edge_scenarios(kind):
    data = synthetic_scenario()
    if kind == "zero_capacity":
        data["battery"].update(capacity_kwh=0, initial_energy_kwh=0)
    for h in data["hours"]:
        if kind == "zero_demand":
            h["demand_kwh"] = 0
        if kind == "zero_tariff":
            h["tariff_bdt_per_kwh"] = 0
        if kind == "excess_solar":
            h["solar_kwh"] = 100
    _, result = solve(data, [make_directive()])
    if kind != "zero_capacity":
        assert result.total_cost_bdt == pytest.approx(0)


def test_infeasible_is_controlled():
    data = synthetic_scenario()
    with pytest.raises(OptimizationError):
        solve(
            data, [make_directive("max_grid_window", {"hours": list(range(24)), "max_grid_kwh": 0})]
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: setattr(r.hourly_plan[0], "grid_kwh", r.hourly_plan[0].grid_kwh + 1),
        lambda r: setattr(r.hourly_plan[0], "solar_used_kwh", 1),
        lambda r: setattr(r.hourly_plan[0], "battery_energy_after_kwh", 100),
        lambda r: setattr(r.hourly_plan[0], "battery_kwh", 100),
        lambda r: setattr(r, "total_grid_kwh", r.total_grid_kwh + 1),
        lambda r: setattr(r, "total_cost_bdt", r.total_cost_bdt + 1),
        lambda r: setattr(r, "peak_grid_kwh", r.peak_grid_kwh + 1),
        lambda r: setattr(r, "scenario_id", "wrong"),
    ],
)
def test_replay_detects_corruption(mutation):
    scenario, result = solve(synthetic_scenario(), [make_directive()])
    mutation(result)
    with pytest.raises(ReplayError):
        validate_plan(scenario, result)


def test_replay_detects_neutrality_even_with_balanced_energy():
    scenario, result = solve(synthetic_scenario(), [make_directive()])
    p = result.hourly_plan[-1]
    before = result.hourly_plan[-2].battery_energy_after_kwh
    flow = 1 - before
    p.battery_action = "charge" if flow >= 0 else "discharge"
    p.battery_kwh = abs(flow)
    p.grid_kwh = 4 + flow
    p.battery_energy_after_kwh = 1
    with pytest.raises(ReplayError, match="neutrality"):
        validate_plan(scenario, result)


@pytest.mark.parametrize(
    "kind,adjustment",
    [
        ("no_charge_window", {"hours": list(range(24))}),
        ("no_discharge_window", {"hours": list(range(24))}),
        ("minimum_battery_reserve", {"hours": list(range(24)), "minimum_energy_kwh": 4}),
        ("max_grid_window", {"hours": list(range(24)), "max_grid_kwh": 0}),
    ],
)
def test_independent_replay_rejects_unapplied_directive(kind, adjustment):
    scenario, result = solve(synthetic_scenario(), [make_directive()])
    result.directive_interpretation = validate_directives(
        {"directive_interpretation": [make_directive(kind, adjustment)]}, scenario
    )
    with pytest.raises(ReplayError):
        validate_plan(scenario, result)


def test_replay_rejects_unapplied_solar():
    data = synthetic_scenario()
    for h in data["hours"]:
        h["solar_kwh"] = 2
    scenario, result = solve(data, [make_directive()])
    result.directive_interpretation = validate_directives(
        {
            "directive_interpretation": [
                make_directive("solar_reduction", {"hours": list(range(24)), "factor": 0})
            ]
        },
        scenario,
    )
    with pytest.raises(ReplayError, match="solar"):
        validate_plan(scenario, result)


def exhaustive_cost(data: dict, raw: list[dict]) -> float:
    """Independent integer-state dynamic program, not a linear optimizer.

    Integral bounds and supplies imply an integral network-flow optimum for these fixtures.
    Enumerate every reachable end-of-hour energy and action; solar is free and tariffs >= 0.
    """
    b = data["battery"]
    states = {b["initial_energy_kwh"]: 0.0}
    for hour in data["hours"]:
        h = hour["hour"]
        solar, reserve, cap = hour["solar_kwh"], b["minimum_energy_kwh"], math.inf
        no_charge = no_discharge = False
        for d in raw:
            a = d["structured_adjustment"]
            if a is None or h not in a["hours"]:
                continue
            kind = d["directive_type"]
            if kind == "solar_reduction":
                solar = hour["solar_kwh"] * a["factor"]
            if kind == "minimum_battery_reserve":
                reserve = max(reserve, a["minimum_energy_kwh"])
            if kind == "max_grid_window":
                cap = min(cap, a["max_grid_kwh"])
            no_charge |= kind == "no_charge_window"
            no_discharge |= kind == "no_discharge_window"
        next_states = {}
        for before, cost in states.items():
            for after in range(int(reserve), b["capacity_kwh"] + 1):
                flow = after - before
                if flow > (0 if no_charge else b["max_charge_kwh_per_hour"]):
                    continue
                if -flow > (0 if no_discharge else b["max_discharge_kwh_per_hour"]):
                    continue
                # Negative demand+flow requires grid export even if solar is curtailed.
                if hour["demand_kwh"] + flow < 0:
                    continue
                grid = max(0, hour["demand_kwh"] + flow - solar)
                if grid > cap:
                    continue
                value = cost + grid * hour["tariff_bdt_per_kwh"]
                next_states[after] = min(next_states.get(after, math.inf), value)
        states = next_states
    return states.get(b["initial_energy_kwh"], math.inf)


@pytest.mark.parametrize("seed", range(50))
def test_randomized_against_exhaustive_oracle(seed):
    rng = random.Random(seed)
    data = synthetic_scenario()
    data["operator_notes"] *= 3
    for h in data["hours"]:
        h.update(
            demand_kwh=rng.randrange(5),
            solar_kwh=2 * rng.randrange(4),
            tariff_bdt_per_kwh=rng.randrange(6),
        )
    kinds = [
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    ]
    directives = []
    for i in range(3):
        kind = rng.choice(kinds)
        adjustment = {"hours": sorted(rng.sample(range(24), 4))}
        if kind == "solar_reduction":
            adjustment["factor"] = rng.choice([0, 0.5, 1])
        if kind == "minimum_battery_reserve":
            adjustment["minimum_energy_kwh"] = rng.randrange(5)
        if kind == "max_grid_window":
            adjustment["max_grid_kwh"] = rng.randrange(6)
        directives.append(make_directive(kind, None if kind == "no_op" else adjustment, i))
    expected = exhaustive_cost(data, directives)
    if math.isinf(expected):
        with pytest.raises(OptimizationError):
            solve(data, directives)
    else:
        _, result = solve(data, directives)
        assert result.total_cost_bdt == pytest.approx(expected, abs=1e-7)
        # A second solve of the same input must return the same result on this pinned solver.
        _, repeated = solve(data, directives)
        assert result.model_dump() == repeated.model_dump()
