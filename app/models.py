from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
HourNumber = Annotated[int, Field(ge=0, le=23, strict=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Hour(StrictModel):
    hour: HourNumber
    demand_kwh: Nonnegative
    solar_kwh: Nonnegative
    tariff_bdt_per_kwh: Nonnegative


class Battery(StrictModel):
    capacity_kwh: Nonnegative
    initial_energy_kwh: Nonnegative
    minimum_energy_kwh: Nonnegative
    max_charge_kwh_per_hour: Nonnegative
    max_discharge_kwh_per_hour: Nonnegative

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if not self.minimum_energy_kwh <= self.initial_energy_kwh <= self.capacity_kwh:
            raise ValueError("require minimum <= initial <= capacity")
        return self


class Scenario(StrictModel):
    scenario_id: str
    operator_notes: Annotated[list[str], Field(min_length=1, max_length=3)]
    hours: Annotated[list[Hour], Field(min_length=24, max_length=24)]
    battery: Battery

    @field_validator("operator_notes")
    @classmethod
    def nonempty_notes(cls, notes: list[str]) -> list[str]:
        if any(not note.strip() for note in notes):
            raise ValueError("notes must be non-empty")
        return notes

    @field_validator("hours")
    @classmethod
    def complete_hours(cls, hours: list[Hour]) -> list[Hour]:
        if sorted(h.hour for h in hours) != list(range(24)):
            raise ValueError("hours must contain exactly 0 through 23")
        return sorted(hours, key=lambda h: h.hour)


class HoursAdjustment(StrictModel):
    hours: Annotated[list[HourNumber], Field(min_length=1, max_length=24)]

    @field_validator("hours")
    @classmethod
    def sorted_unique(cls, hours: list[int]) -> list[int]:
        if hours != sorted(set(hours)):
            raise ValueError("hours must be unique and sorted")
        return hours


class SolarAdjustment(HoursAdjustment):
    factor: Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)]


class ReserveAdjustment(HoursAdjustment):
    minimum_energy_kwh: Nonnegative


class GridAdjustment(HoursAdjustment):
    max_grid_kwh: Nonnegative


class DirectiveBase(StrictModel):
    note_index: Annotated[int, Field(ge=0, strict=True)]
    explanation: str

    @model_validator(mode="before")
    @classmethod
    def strict_applies(cls, value: object) -> object:
        if isinstance(value, dict) and type(value.get("applies")) is not bool:
            raise ValueError("applies must be a JSON boolean")
        return value


class SolarDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal["solar_reduction"]
    structured_adjustment: SolarAdjustment


class ReserveDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal["minimum_battery_reserve"]
    structured_adjustment: ReserveAdjustment


class NoChargeDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal["no_charge_window"]
    structured_adjustment: HoursAdjustment


class NoDischargeDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal["no_discharge_window"]
    structured_adjustment: HoursAdjustment


class GridDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal["max_grid_window"]
    structured_adjustment: GridAdjustment


class NoOpDirective(DirectiveBase):
    applies: Literal[False]
    directive_type: Literal["no_op"]
    structured_adjustment: None


Directive = Annotated[
    SolarDirective
    | ReserveDirective
    | NoChargeDirective
    | NoDischargeDirective
    | GridDirective
    | NoOpDirective,
    Field(discriminator="directive_type"),
]


class Interpretation(StrictModel):
    directive_interpretation: Annotated[list[Directive], Field(min_length=1, max_length=3)]


class PlanHour(StrictModel):
    hour: HourNumber
    grid_kwh: Nonnegative
    solar_used_kwh: Nonnegative
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: Nonnegative
    battery_energy_after_kwh: Nonnegative


class OptimizationResponse(Interpretation):
    scenario_id: str
    hourly_plan: Annotated[list[PlanHour], Field(min_length=24, max_length=24)]
    total_grid_kwh: Nonnegative
    total_cost_bdt: Nonnegative
    peak_grid_kwh: Nonnegative
    plan_summary: str

    @field_validator("hourly_plan")
    @classmethod
    def ordered_plan(cls, plan: list[PlanHour]) -> list[PlanHour]:
        if [h.hour for h in plan] != list(range(24)):
            raise ValueError("plan must be in hour order 0 through 23")
        return plan
