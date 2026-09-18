import asyncio
import time

import httpx
import pytest

from app.errors import InterpretationError
from tests.test_interpreter import run_interpreter


@pytest.mark.parametrize(
    "envelope",
    [
        None,
        [],
        "text",
        {},
        {"choices": []},
        {"choices": None},
        {"choices": [None]},
        {"choices": [{}]},
        {"choices": [{"message": []}]},
        {"choices": [{"message": {"content": 7}, "finish_reason": "stop"}]},
    ],
)
def test_malformed_envelopes_have_one_repair(settings, scenario, envelope):
    run, calls = run_interpreter(settings, scenario, [httpx.Response(200, json=envelope)])
    with pytest.raises(InterpretationError):
        run()
    assert len(calls) == 2


def test_positive_retry_after_waits_before_retry(settings, scenario, case):
    replies = [
        httpx.Response(429, headers={"retry-after": "0.02"}),
        {"directive_interpretation": case["expected_output"]["directive_interpretation"]},
    ]
    run, calls = run_interpreter(settings, scenario, replies)
    start = time.monotonic()
    assert len(run()) == 2
    assert time.monotonic() - start >= 0.02
    assert len(calls) == 2


def test_retry_after_cannot_consume_remaining_deadline(settings, scenario, monkeypatch):
    settings.llm_timeout_seconds = 0.06
    sleep = []

    async def forbidden_sleep(delay):
        sleep.append(delay)
        raise AssertionError("cannot sleep past the retry budget")

    monkeypatch.setattr(asyncio, "sleep", forbidden_sleep)
    run, calls = run_interpreter(
        settings, scenario, [httpx.Response(429, headers={"retry-after": "0.02"})]
    )
    with pytest.raises(InterpretationError):
        run()
    assert len(calls) == 1 and not sleep
