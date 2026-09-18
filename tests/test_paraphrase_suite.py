import asyncio
import os
from collections import Counter

import pytest

from app.config import Settings
from app.guardrails import validate_directives
from app.optimizer import optimize
from app.validator import validate_plan
from scripts.run_live_benchmark import benchmark, load_suite, make_scenario


def test_synthetic_suite_shape_and_offline_pipeline():
    suite = load_suite()
    assert len(suite["requests"]) == 16
    assert sum(len(item["notes"]) for item in suite["requests"]) == 48
    counts = Counter()
    for item in suite["requests"]:
        assert len(item["notes"]) == len(item["expected"]) == 3
        scenario = make_scenario(item, suite["battery_capacity_kwh"])
        directives = validate_directives(
            {"directive_interpretation": item["expected"]}, scenario
        )
        response = optimize(scenario, directives)
        validate_plan(scenario, response)
        counts.update(directive.directive_type for directive in directives)
    assert counts == {
        "solar_reduction": 8,
        "minimum_battery_reserve": 8,
        "no_charge_window": 8,
        "no_discharge_window": 8,
        "max_grid_window": 8,
        "no_op": 8,
    }


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_LLM") != "1", reason="live LLM explicitly opt-in only")
def test_live_synthetic_paraphrases():
    settings = Settings.from_env()
    if not settings.configured:
        pytest.skip("LLM_API_KEY must be configured")
    result, passed = asyncio.run(benchmark(settings))
    assert passed, result
