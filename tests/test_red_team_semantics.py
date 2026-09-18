"""Adversarial semantic cases kept separate from organizer and earlier synthetic data."""

import asyncio
import json
import os
from collections import Counter
from pathlib import Path

import httpx
import pytest

from app.interpreter import LLMInterpreter
from app.optimizer import optimize
from app.validator import validate_plan
from scripts.run_live_benchmark import benchmark, make_scenario
from scripts.run_public_cases import compare_semantics

SUITE_PATH = Path(__file__).parent / "data/semantic_red_team_cases.json"
SUITE = json.loads(SUITE_PATH.read_text())


def test_red_team_fixture_coverage():
    requests = SUITE["requests"]
    directives = [directive for item in requests for directive in item["expected"]]
    counts = Counter(directive["directive_type"] for directive in directives)
    tags = {tag for item in requests for tag in item["tags"]}

    assert len(requests) == 18
    assert len(directives) == 54
    assert set(counts) == {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }
    assert {
        "percentage",
        "time",
        "negation",
        "soft-language",
        "quoted",
        "hypothetical",
        "adversarial",
        "numeric",
        "multi-note",
    } <= tags
    assert all(len(item["notes"]) == len(item["expected"]) == 3 for item in requests)
    assert len({item["id"] for item in requests}) == len(requests)


@pytest.mark.parametrize("item", SUITE["requests"], ids=lambda item: item["id"])
def test_red_team_mocked_interpretation_and_full_pipeline(settings, item):
    scenario = make_scenario(item, SUITE["battery_capacity_kwh"])

    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        supplied = json.loads(payload["messages"][1]["content"])
        assert supplied == {
            "operator_notes": item["notes"],
            "battery_capacity_kwh": SUITE["battery_capacity_kwh"],
        }
        wire = []
        for directive in item["expected"]:
            adjustment = {
                "hours": [],
                "factor": None,
                "minimum_energy_kwh": None,
                "max_grid_kwh": None,
            }
            adjustment.update(directive["structured_adjustment"] or {})
            wire.append({**directive, "structured_adjustment": adjustment})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"directive_interpretation": wire})
                        },
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await LLMInterpreter(settings, client).interpret(scenario)

    directives = asyncio.run(run())
    compare_semantics([directive.model_dump() for directive in directives], item["expected"])
    validate_plan(scenario, optimize(scenario, directives))


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_LLM") != "1", reason="live LLM explicitly opt-in only")
def test_live_red_team_semantics():
    from app.config import Settings

    result, passed = asyncio.run(
        benchmark(Settings.from_env(), pace_seconds=7.5, suite_path=SUITE_PATH)
    )
    assert passed, result
    assert result["notes"] == 54
    assert result["correct_notes"] == 54
