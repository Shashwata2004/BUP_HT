"""Prove benchmark accounting using synthetic provider responses, never network calls."""

import asyncio
from copy import deepcopy

import pytest

from app.errors import InterpretationError
from app.guardrails import validate_directives
from scripts import run_live_benchmark as runner


def install_fake(monkeypatch, mode):
    source = runner.load_suite()
    cases = source["requests"][:1]
    monkeypatch.setattr(runner, "load_suite", lambda: {**source, "requests": cases})

    async def interpret(self, scenario, metrics):
        metrics.provider_calls = 1
        if mode == "unavailable":
            metrics.client_failures = 1
            raise InterpretationError("model provider unavailable")
        raw = deepcopy(cases[0]["expected"])
        if mode == "wrong_one_note":
            raw[0]["structured_adjustment"]["factor"] = 0.3
        if mode == "retries":
            metrics.provider_calls = 3
            metrics.transient_retries = 1
            metrics.validation_repairs = 1
            metrics.invalid_outputs = 1
        return validate_directives({"directive_interpretation": raw}, scenario)

    monkeypatch.setattr(runner.LLMInterpreter, "interpret", interpret)
    return source, cases


def test_benchmark_counts_individual_semantics_even_if_replay_fails(monkeypatch, settings):
    install_fake(monkeypatch, "wrong_one_note")
    result, passed = asyncio.run(runner.benchmark(settings, pace_seconds=0))
    assert not passed
    assert result["notes"] == 3
    assert result["correct_notes"] == 2
    assert result["type_accuracy_percent"] == 100
    assert result["time_window_accuracy_percent"] == 100
    assert result["numeric_accuracy_percent"] == 66.67


def test_benchmark_reports_one_retry_request_for_two_retry_reasons(monkeypatch, settings):
    install_fake(monkeypatch, "retries")
    result, passed = asyncio.run(runner.benchmark(settings, pace_seconds=0))
    assert passed
    assert result["provider_calls"] == 3
    assert result["retry_request_rate_percent"] == 100
    assert result["invalid_output_rate_per_call_percent"] == 33.33


def test_benchmark_stops_on_bad_credentials_without_burning_rest(monkeypatch, settings):
    source, _ = install_fake(monkeypatch, "unavailable")
    monkeypatch.setattr(runner, "load_suite", lambda: source)
    result, passed = asyncio.run(runner.benchmark(settings, pace_seconds=0))
    assert not passed
    assert result["provider_calls"] == 1
    assert result["requests"] == 1
    assert result["unattempted_requests"] == 15
    assert result["latency_seconds"]["max"] >= 0


@pytest.mark.parametrize("pace", [-1, float("nan"), float("inf"), 100])
def test_invalid_pacing_rejected_before_calls(settings, pace):
    with pytest.raises(ValueError, match="pace_seconds"):
        asyncio.run(runner.benchmark(settings, pace_seconds=pace))


def test_unknown_request_id_rejected_before_calls(settings):
    with pytest.raises(ValueError, match="request ID"):
        asyncio.run(runner.benchmark(settings, request_ids={"not-a-case"}))
