import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import InterpretationError, ReplayError
from app.guardrails import validate_directives
from app.main import create_app
from app.models import OptimizationResponse, Scenario
from scripts.run_public_cases import verify_case


def test_health_and_post(settings, case):
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/health").status_code == 200
        directives = validate_directives(
            {"directive_interpretation": case["expected_output"]["directive_interpretation"]},
            Scenario.model_validate(case["input"]),
        )
        app.state.interpreter.interpret = AsyncMock(return_value=directives)
        result = client.post("/optimize-energy", json=case["input"])
        assert result.status_code == 200
        response = OptimizationResponse.model_validate(result.json())
        verify_case(case, response)
        assert set(result.json()) == set(case["expected_output"])
        assert set(result.json()["hourly_plan"][0]) == set(
            case["expected_output"]["hourly_plan"][0]
        )
        assert app.state.interpreter.interpret.await_count == 1


def test_missing_config_not_ready(case):
    with TestClient(create_app(Settings())) as client:
        assert client.get("/health").status_code == 500
        assert client.post("/optimize-energy", json=case["input"]).json() == {"error": "not_ready"}


@pytest.mark.parametrize("body", ["{", "[]", "{}", "null", "true", '{"hours":NaN}'])
def test_malformed_requests(settings, body):
    with TestClient(create_app(settings)) as client:
        result = client.post(
            "/optimize-energy", content=body, headers={"Content-Type": "application/json"}
        )
        assert result.status_code == 400
        assert result.json() == {"error": "invalid_request"}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(operator_notes=[]),
        lambda d: d.update(operator_notes=[" "]),
        lambda d: d.update(operator_notes=["x"] * 4),
        lambda d: d.update(operator_notes=[123]),
        lambda d: d.update(hours=d["hours"][:23]),
        lambda d: d["hours"][0].update(hour=1),
        lambda d: d["hours"][0].update(hour=True),
        lambda d: d["hours"][0].update(hour=0.0),
        lambda d: d["hours"][0].update(demand_kwh=-1),
        lambda d: d["hours"][0].update(solar_kwh=float("nan")),
        lambda d: d["hours"][0].update(tariff_bdt_per_kwh=float("inf")),
        lambda d: d["hours"][0].update(demand_kwh="123"),
        lambda d: d["hours"][0].update(solar_kwh=True),
        lambda d: d["battery"].update(initial_energy_kwh=10000),
        lambda d: d["battery"].update(minimum_energy_kwh=200),
        lambda d: d["battery"].update(max_charge_kwh_per_hour=-1),
        lambda d: d.update(extra="not allowed"),
        lambda d: d.pop("scenario_id"),
    ],
)
def test_request_schema(settings, case, mutation):
    mutation(case["input"])
    with TestClient(create_app(settings)) as client:
        result = client.post(
            "/optimize-energy",
            content=json.dumps(case["input"]),
            headers={"Content-Type": "application/json"},
        )
        assert result.status_code == 400


def test_unsorted_request_hours_accepted(case):
    case["input"]["hours"].reverse()
    assert [h.hour for h in Scenario.model_validate(case["input"]).hours] == list(range(24))


@pytest.mark.parametrize(
    "error",
    [
        InterpretationError("secret-test-value"),
        RuntimeError("secret-test-value"),
        ReplayError("secret-test-value"),
    ],
)
def test_errors_do_not_leak(settings, case, error, caplog):
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.interpreter.interpret = AsyncMock(side_effect=error)
        result = client.post("/optimize-energy", json=case["input"])
        assert result.status_code == 500
        assert "secret-test-value" not in result.text + caplog.text
        assert "Traceback" not in result.text + caplog.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_cost_bdt", -1),
        ("total_grid_kwh", float("nan")),
        ("peak_grid_kwh", "2"),
        ("extra", 2),
    ],
)
def test_response_schema(case, field, value):
    case["expected_output"][field] = value
    with pytest.raises(ValidationError):
        OptimizationResponse.model_validate(case["expected_output"])


def test_invalid_config_does_not_log_secret(monkeypatch, caplog):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "secret-test-value")
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 500
    assert "secret-test-value" not in caplog.text


def test_pipeline_deadline(settings, case):
    import asyncio

    settings.request_timeout_seconds = 0.01
    app = create_app(settings)

    async def slow_model(_):
        await asyncio.sleep(0.1)
        raise AssertionError("request should already be cancelled")

    with TestClient(app) as client:
        app.state.interpreter.interpret = slow_model
        result = client.post("/optimize-energy", json=case["input"])
        assert result.status_code == 500
        assert result.json() == {"error": "request_timeout"}
