"""Systematic malformed-input rejection and mixed concurrent request isolation."""

import asyncio
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import OptimizationResponse, Scenario
from app.validator import validate_plan
from tests.conftest import make_directive
from tests.test_optimizer import synthetic_scenario


def mutations():
    result = []
    for key in ("scenario_id", "operator_notes", "hours", "battery"):
        result.append((key, "missing"))
        for value in (None, True, 7, {}, [None]):
            result.append((key, value))
    for key in (
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    ):
        for value in (None, "4", True, -0.1, float("nan"), float("inf"), -float("inf"), "missing"):
            result.append(("battery." + key, value))
    for key in ("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"):
        for value in (None, "4", True, -0.1, float("nan"), float("inf"), [], "missing"):
            result.append(("hour." + key, value))
    for value in (-1, 24, 0.5, "0", True, None, "missing"):
        result.append(("hour.hour", value))
    for value in ([], [""], ["  \n"], ["x"] * 4, "text", [False], [["x"]]):
        result.append(("operator_notes", value))
    return result


@pytest.mark.parametrize("path,value", mutations())
def test_systematic_schema_fuzz(settings, monkeypatch, path, value):
    body = synthetic_scenario()
    obj = body
    if path.startswith("battery."):
        obj, path = body["battery"], path.split(".")[1]
    elif path.startswith("hour."):
        obj, path = body["hours"][0], path.split(".")[1]
    if value == "missing":
        obj.pop(path)
    else:
        obj[path] = value
    solver = Mock(side_effect=AssertionError("invalid input reached optimizer"))
    monkeypatch.setattr("app.main.optimize", solver)
    app = create_app(settings)
    with TestClient(app) as client:
        interpreter = AsyncMock(side_effect=AssertionError("invalid input reached LLM"))
        app.state.interpreter.interpret = interpreter
        response = client.post(
            "/optimize-energy",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_request"}
        interpreter.assert_not_awaited()
        solver.assert_not_called()
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b'{"scenario_id":',
        b"null",
        b"42",
        b"\xff",
        b"[[]]",
        b'{"scenario_id":"sentinel-private-value",}',
    ],
)
def test_broken_json_is_contained(settings, body):
    app = create_app(settings)
    with TestClient(app) as client:
        interpreter = AsyncMock()
        app.state.interpreter.interpret = interpreter
        response = client.post(
            "/optimize-energy", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert "sentinel-private-value" not in response.text
        assert "Traceback" not in response.text
        interpreter.assert_not_awaited()


def test_100_concurrent_mixed_requests_and_failure_recovery(settings):
    calls = Counter()

    async def provider(request):
        supplied = json.loads(json.loads(request.content)["messages"][1]["content"])
        # A test-only ID carried in untrusted notes selects deterministic mock behavior.
        identifier = supplied["operator_notes"][0]
        calls[identifier] += 1
        await asyncio.sleep(0.001 * (int(identifier) % 4))
        if int(identifier) % 10 == 0 and calls[identifier] == 1:
            return httpx.Response(503, text="sentinel-private-value")
        raw = [make_directive(index=i) for i in range(len(supplied["operator_notes"]))]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"directive_interpretation": raw})},
                    }
                ]
            },
        )

    app = create_app(settings)
    with TestClient(app) as client:
        app.state.interpreter.client = httpx.AsyncClient(transport=httpx.MockTransport(provider))

        def post(index):
            data = deepcopy(synthetic_scenario())
            data.update(
                scenario_id=f"concurrent-{index}", operator_notes=[str(index)] * (1 + index % 3)
            )
            for h in data["hours"]:
                h["demand_kwh"] += index / 100
            start = time.perf_counter()
            response = client.post("/optimize-energy", json=data)
            assert response.status_code == 200
            parsed = OptimizationResponse.model_validate(response.json())
            validate_plan(Scenario.model_validate(data), parsed)
            assert parsed.scenario_id == data["scenario_id"]
            return time.perf_counter() - start

        with ThreadPoolExecutor(max_workers=16) as pool:
            elapsed = list(pool.map(post, range(100)))
        assert len(elapsed) == 100
        assert sum(calls.values()) == 110
        assert max(calls.values()) == 2
        assert client.get("/health").json() == {"status": "ok"}
