import asyncio
import os

import httpx
import pytest

from app.config import Settings
from app.guardrails import validate_directives
from app.interpreter import LLMInterpreter
from app.models import OptimizationResponse, Scenario
from app.optimizer import optimize
from app.validator import validate_plan
from scripts.run_public_cases import load_cases, verify_case

CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_official_optima(case):
    scenario = Scenario.model_validate(case["input"])
    directives = validate_directives(
        {"directive_interpretation": case["expected_output"]["directive_interpretation"]}, scenario
    )
    result = optimize(scenario, directives)
    assert abs(verify_case(case, result)) <= 0.01
    validate_plan(scenario, OptimizationResponse.model_validate_json(result.model_dump_json()))
    validate_plan(scenario, OptimizationResponse.model_validate(case["expected_output"]))


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_LLM") != "1", reason="live LLM explicitly opt-in only")
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_live_public_cases(case):
    settings = Settings.from_env()
    if not settings.configured:
        pytest.skip("LLM_API_KEY and LLM_MODEL must be configured")

    async def run():
        scenario = Scenario.model_validate(case["input"])
        async with httpx.AsyncClient(trust_env=False) as client:
            directives = await LLMInterpreter(settings, client).interpret(scenario)
        verify_case(case, optimize(scenario, directives))

    asyncio.run(run())
