import pytest

from app.config import Settings
from app.models import Scenario


@pytest.fixture
def case():
    """Independent synthetic fixture; general tests do not need organizer files.

    Flat tariffs, full solar use, and battery neutrality certify this idle plan's
    optimum directly from energy balance, without calling our optimizer.
    """
    plan = [
        {
            "hour": h,
            "grid_kwh": 9 if h in (8, 9) else 8,
            "solar_used_kwh": 1 if h in (8, 9) else 2,
            "battery_action": "idle",
            "battery_kwh": 0,
            "battery_energy_after_kwh": 150,
        }
        for h in range(24)
    ]
    return {
        "id": "synthetic-fixture",
        "input": {
            "scenario_id": "synthetic-fixture",
            "operator_notes": [
                "PV will provide half its forecast from 08:00 to 10:00.",
                "The chess club meets next month.",
            ],
            "hours": [
                {"hour": h, "demand_kwh": 10, "solar_kwh": 2, "tariff_bdt_per_kwh": 3}
                for h in range(24)
            ],
            "battery": {
                "capacity_kwh": 300,
                "initial_energy_kwh": 150,
                "minimum_energy_kwh": 50,
                "max_charge_kwh_per_hour": 20,
                "max_discharge_kwh_per_hour": 20,
            },
        },
        "expected_output": {
            "scenario_id": "synthetic-fixture",
            "directive_interpretation": [
                make_directive("solar_reduction", {"hours": [8, 9], "factor": 0.5}),
                make_directive(index=1),
            ],
            "hourly_plan": plan,
            "total_grid_kwh": 194,
            "total_cost_bdt": 582,
            "peak_grid_kwh": 9,
            "plan_summary": "Use available solar and preserve battery energy at a flat tariff.",
        },
    }


@pytest.fixture
def scenario(case):
    return Scenario.model_validate(case["input"])


@pytest.fixture
def settings():
    return Settings(llm_api_key="test-placeholder", llm_model="mock-model")


def make_directive(kind="no_op", adjustment=None, index=0):
    return {
        "note_index": index,
        "applies": kind != "no_op",
        "directive_type": kind,
        "structured_adjustment": adjustment,
        "explanation": "Synthetic test directive.",
    }
