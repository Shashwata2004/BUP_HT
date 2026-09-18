from math import fsum

import numpy as np
from scipy.optimize import linprog

from app.errors import OptimizationError
from app.guardrails import validate_directives
from app.models import Directive, OptimizationResponse, PlanHour, Scenario


def optimize(scenario: Scenario, directives: list[Directive]) -> OptimizationResponse:
    directives = validate_directives(
        {"directive_interpretation": [d.model_dump() for d in directives]}, scenario
    )
    b = scenario.battery
    solar = [h.solar_kwh for h in scenario.hours]
    reserve = [b.minimum_energy_kwh] * 24
    charge = [b.max_charge_kwh_per_hour] * 24
    discharge = [b.max_discharge_kwh_per_hour] * 24
    grid_caps: list[float | None] = [None] * 24
    for d in directives:
        a = d.structured_adjustment
        if d.directive_type == "no_op":
            continue
        assert a is not None
        for h in a.hours:
            if d.directive_type == "solar_reduction":
                # Literal canonical assignment: original solar times factor, in note order.
                solar[h] = scenario.hours[h].solar_kwh * d.structured_adjustment.factor
            elif d.directive_type == "minimum_battery_reserve":
                reserve[h] = max(reserve[h], d.structured_adjustment.minimum_energy_kwh)
            elif d.directive_type == "no_charge_window":
                charge[h] = 0.0
            elif d.directive_type == "no_discharge_window":
                discharge[h] = 0.0
            elif d.directive_type == "max_grid_window":
                cap = d.structured_adjustment.max_grid_kwh
                grid_caps[h] = cap if grid_caps[h] is None else min(grid_caps[h], cap)

    # x = [grid[24], solar_used[24], signed_battery_flow[24], energy_after[24]].
    # Positive flow is charging, negative is discharging: simultaneous actions are impossible.
    objective = np.zeros(96)
    objective[:24] = [h.tariff_bdt_per_kwh for h in scenario.hours]
    equalities = np.zeros((49, 96))
    rhs = np.zeros(49)
    for h in range(24):
        equalities[h, h] = 1
        equalities[h, 24 + h] = 1
        equalities[h, 48 + h] = -1
        rhs[h] = scenario.hours[h].demand_kwh
        equalities[24 + h, 72 + h] = 1
        equalities[24 + h, 48 + h] = -1
        if h:
            equalities[24 + h, 71 + h] = -1
        else:
            rhs[24 + h] = b.initial_energy_kwh
    equalities[48, 95] = 1
    rhs[48] = b.initial_energy_kwh
    bounds = (
        [(0, cap) for cap in grid_caps]
        + [(0, value) for value in solar]
        + [(-discharge[h], charge[h]) for h in range(24)]
        + [(reserve[h], b.capacity_kwh) for h in range(24)]
    )
    result = linprog(
        objective,
        A_eq=equalities,
        b_eq=rhs,
        bounds=bounds,
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-9,
            "dual_feasibility_tolerance": 1e-9,
            "time_limit": 2.0,
        },
    )
    if not result.success or result.x is None or not np.all(np.isfinite(result.x)):
        raise OptimizationError("no certified optimal schedule")
    plan: list[PlanHour] = []
    energy = b.initial_energy_kwh
    for h in range(24):
        flow = float(result.x[48 + h])
        # Preserve all nonzero flows; only remove negative-zero artifacts on nonnegative fields.
        energy += flow
        plan.append(
            PlanHour(
                hour=h,
                grid_kwh=max(0.0, float(result.x[h])),
                solar_used_kwh=max(0.0, float(result.x[24 + h])),
                battery_action="charge" if flow > 0 else "discharge" if flow < 0 else "idle",
                battery_kwh=abs(flow),
                battery_energy_after_kwh=max(0.0, energy),
            )
        )
    response = OptimizationResponse(
        scenario_id=scenario.scenario_id,
        directive_interpretation=directives,
        hourly_plan=plan,
        total_grid_kwh=fsum(h.grid_kwh for h in plan),
        total_cost_bdt=fsum(h.grid_kwh * scenario.hours[h.hour].tariff_bdt_per_kwh for h in plan),
        peak_grid_kwh=max(h.grid_kwh for h in plan),
        plan_summary=(
            "Minimizes grid electricity cost while applying all operating directives, "
            "respecting battery limits, and restoring initial battery energy."
        ),
    )
    from app.validator import validate_plan

    validate_plan(scenario, response)
    return response
