import asyncio
from pathlib import Path

import pytest

from app.guardrails import validate_directives
from scripts import run_burst_benchmark, run_live_benchmark, smoke_test


def test_alternate_live_suite_path(settings, monkeypatch):
    suite_path = Path(__file__).parent / "data/semantic_hidden_style_cases.json"
    import json

    item = json.loads(suite_path.read_text())["requests"][0]

    async def interpret(self, scenario, metrics):
        metrics.provider_calls = 1
        return validate_directives({"directive_interpretation": item["expected"]}, scenario)

    monkeypatch.setattr(run_live_benchmark.LLMInterpreter, "interpret", interpret)
    result, passed = asyncio.run(
        run_live_benchmark.benchmark(
            settings, pace_seconds=0, request_ids={item["id"]}, suite_path=suite_path
        )
    )
    assert passed and result["correct_notes"] == 3 and result["provider_calls"] == 1


@pytest.mark.parametrize(
    "live,count,workers", [(True, 4, 1), (False, 101, 8), (False, 0, 8), (False, 2, 17)]
)
def test_smoke_limits_before_startup(live, count, workers):
    with pytest.raises(ValueError):
        smoke_test.run(None, live, count, workers)


def test_burst_counts_recovered_429_and_server_errors(settings, monkeypatch):
    import httpx

    real_client = httpx.AsyncClient
    calls = {}

    def provider(request):
        import json

        from tests.test_hidden_semantics import SUITE

        notes = json.loads(json.loads(request.content)["messages"][1]["content"])["operator_notes"]
        item = next(r for r in SUITE["requests"] if r["notes"] == notes)
        calls[item["id"]] = calls.get(item["id"], 0) + 1
        if calls[item["id"]] == 1:
            return httpx.Response(
                429 if item["id"].endswith("a") else 503, headers={"retry-after": "0"}
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps({"directive_interpretation": item["expected"]})
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(
        run_burst_benchmark.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(provider), **kwargs),
    )
    result, passed = asyncio.run(run_burst_benchmark.benchmark(settings))
    assert passed and result["successes"] == 2
    assert result["provider_calls"] == 4
    assert result["provider_429_responses"] == result["provider_5xx_responses"] == 1
    assert result["transient_retries"] == 2
