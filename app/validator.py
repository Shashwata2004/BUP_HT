"""Independent replay: no optimizer arrays or solver state are used here."""

from math import fsum, isclose

from app.errors import ReplayError
from app.guardrails import validate_directives
from app.models import OptimizationResponse, Scenario

# Deliberately stricter than the official 0.01 absolute tolerance.
REPLAY_TOLERANCE = 1e-6


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReplayError(code)


def validate_plan(
    scenario: Scenario,
    response: OptimizationResponse,
    tolerance: float = REPLAY_TOLERANCE,
) -> None:
    # Re-validate even if caller used model_copy/model_construct or mutated a nested list.
    response = OptimizationResponse.model_validate(response.model_dump())
    directives = validate_directives(
        {"directive_interpretation": [d.model_dump() for d in response.directive_interpretation]},
        scenario,
    )
    _require(response.scenario_id == scenario.scenario_id, "scenario_id")
    b = scenario.battery
    energy = b.initial_energy_kwh
    for source, p in zip(scenario.hours, response.hourly_plan, strict=True):
        h = source.hour
        _require(h == p.hour, "hour order")
        solar_limit = source.solar_kwh
        active_reserve = b.minimum_energy_kwh
        charging = p.battery_kwh if p.battery_action == "charge" else 0.0
        discharging = p.battery_kwh if p.battery_action == "discharge" else 0.0
        _require(p.battery_action != "idle" or p.battery_kwh == 0, "idle magnitude")
        _require(charging <= b.max_charge_kwh_per_hour + tolerance, "charge rate")
        _require(discharging <= b.max_discharge_kwh_per_hour + tolerance, "discharge rate")
        for d in directives:
            if d.directive_type == "no_op":
                continue
            a = d.structured_adjustment
            assert a is not None
            if h not in a.hours:
                continue
            if d.directive_type == "solar_reduction":
                solar_limit = source.solar_kwh * d.structured_adjustment.factor
            elif d.directive_type == "minimum_battery_reserve":
                active_reserve = max(active_reserve, d.structured_adjustment.minimum_energy_kwh)
            elif d.directive_type == "no_charge_window":
                _require(charging <= tolerance, "no-charge directive")
            elif d.directive_type == "no_discharge_window":
                _require(discharging <= tolerance, "no-discharge directive")
            elif d.directive_type == "max_grid_window":
                _require(p.grid_kwh <= d.structured_adjustment.max_grid_kwh + tolerance, "grid cap")
        _require(p.solar_used_kwh <= solar_limit + tolerance, "effective solar")
        energy += charging - discharging
        _require(
            isclose(energy, p.battery_energy_after_kwh, rel_tol=0, abs_tol=tolerance),
            "battery transition",
        )
        _require(
            active_reserve - tolerance <= energy <= b.capacity_kwh + tolerance,
            "battery bounds/reserve",
        )
        _require(
            isclose(
                p.grid_kwh + p.solar_used_kwh + discharging,
                source.demand_kwh + charging,
                rel_tol=0,
                abs_tol=tolerance,
            ),
            "energy balance",
        )
    _require(isclose(energy, b.initial_energy_kwh, rel_tol=0, abs_tol=tolerance), "neutrality")
    grid = fsum(p.grid_kwh for p in response.hourly_plan)
    cost = fsum(
        p.grid_kwh * scenario.hours[p.hour].tariff_bdt_per_kwh for p in response.hourly_plan
    )
    peak = max(p.grid_kwh for p in response.hourly_plan)
    for actual, reported in [
        (grid, response.total_grid_kwh),
        (cost, response.total_cost_bdt),
        (peak, response.peak_grid_kwh),
    ]:
        _require(isclose(actual, reported, rel_tol=0, abs_tol=tolerance), "reported aggregate")
