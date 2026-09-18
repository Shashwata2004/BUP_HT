"""Offline pipeline checks validate fixtures, not model language understanding."""

import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from app.interpreter import LLMInterpreter
from app.optimizer import optimize
from app.validator import validate_plan
from scripts.run_live_benchmark import make_scenario
from scripts.run_public_cases import compare_semantics

SUITE_PATH = Path(__file__).parent / "data/semantic_hidden_style_cases.json"
SUITE = json.loads(SUITE_PATH.read_text())


def test_hidden_fixture_coverage():
    counts = Counter(d["directive_type"] for r in SUITE["requests"] for d in r["expected"])
    assert len(SUITE["requests"]) == 50
    assert len(counts) == 6 and set(counts.values()) == {25}
    assert sum("adversarial" in r["tags"] for r in SUITE["requests"]) == 10


@pytest.mark.parametrize("item", SUITE["requests"], ids=lambda r: r["id"])
def test_hidden_fixture_mocked_full_pipeline(settings, item):
    scenario = make_scenario(item, SUITE["battery_capacity_kwh"])

    def provider(request):
        payload = json.loads(request.content)
        supplied = json.loads(payload["messages"][1]["content"])
        assert supplied["operator_notes"] == item["notes"]
        wire = []
        for directive in item["expected"]:
            adjustment = dict(hours=[], factor=None, minimum_energy_kwh=None, max_grid_kwh=None)
            adjustment.update(directive["structured_adjustment"] or {})
            wire.append({**directive, "structured_adjustment": adjustment})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"directive_interpretation": wire})},
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await LLMInterpreter(settings, client).interpret(scenario)

    directives = asyncio.run(run())
    compare_semantics([d.model_dump() for d in directives], item["expected"])
    validate_plan(scenario, optimize(scenario, directives))
