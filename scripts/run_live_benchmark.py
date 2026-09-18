#!/usr/bin/env python3
"""Run the tracked synthetic paraphrase suite through the real configured LLM."""

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.guardrails import validate_directives  # noqa: E402
from app.interpreter import InterpretationMetrics, LLMInterpreter  # noqa: E402
from app.models import Scenario  # noqa: E402
from app.optimizer import optimize  # noqa: E402
from app.validator import validate_plan  # noqa: E402
from scripts.run_public_cases import compare_semantics  # noqa: E402

SUITE = ROOT / "tests/data/paraphrase_cases.json"


def load_suite() -> dict:
    return json.loads(SUITE.read_text())


def make_scenario(item: dict, capacity: float) -> Scenario:
    return Scenario.model_validate(
        {
            "scenario_id": "paraphrase-" + item["id"],
            "operator_notes": item["notes"],
            "hours": [
                {
                    "hour": hour,
                    "demand_kwh": 10,
                    "solar_kwh": 3,
                    "tariff_bdt_per_kwh": 2 + (hour % 5),
                }
                for hour in range(24)
            ],
            "battery": {
                "capacity_kwh": capacity,
                "initial_energy_kwh": capacity / 2,
                "minimum_energy_kwh": 20,
                "max_charge_kwh_per_hour": 20,
                "max_discharge_kwh_per_hour": 20,
            },
        }
    )


def _hours(value: dict) -> object:
    adjustment = value.get("structured_adjustment")
    return adjustment.get("hours") if isinstance(adjustment, dict) else None


def _numeric(value: dict) -> object:
    adjustment = value.get("structured_adjustment")
    if not isinstance(adjustment, dict):
        return None
    for key in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if key in adjustment:
            return adjustment[key]
    return None


def _equal_number(left: object, right: object) -> bool:
    if type(left) not in (int, float) or type(right) not in (int, float):
        return left is None and right is None
    return math.isclose(float(left), float(right), rel_tol=0, abs_tol=0.01)


async def benchmark(
    settings: Settings,
    pace_seconds: float = 7.5,
    request_ids: set[str] | None = None,
) -> tuple[dict, bool]:
    if not math.isfinite(pace_seconds) or not 0 <= pace_seconds <= 60:
        raise ValueError("pace_seconds must be finite and between 0 and 60")
    suite = load_suite()
    requests = suite["requests"]
    if request_ids:
        requests = [item for item in requests if item["id"] in request_ids]
        if len(requests) != len(request_ids):
            raise ValueError("unknown or duplicate request ID")
    counts: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    latencies: list[float] = []
    total_metrics = InterpretationMetrics()
    failures: list[str] = []
    retry_requests = 0
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
        interpreter = LLMInterpreter(settings, client)
        for position, item in enumerate(requests):
            scenario = make_scenario(item, suite["battery_capacity_kwh"])
            metrics = InterpretationMetrics()
            start = time.perf_counter()
            actual = []
            try:
                directives = await interpreter.interpret(scenario, metrics)
                actual = [directive.model_dump() for directive in directives]
                response = optimize(scenario, directives)
                validate_plan(scenario, response)
                truth = validate_directives(
                    {"directive_interpretation": item["expected"]}, scenario
                )
                validate_plan(
                    scenario,
                    response.model_copy(update={"directive_interpretation": truth}),
                    tolerance=0.01,
                )
            except Exception as exc:
                failures.append(f"{item['id']}:{type(exc).__name__}")
            else:
                try:
                    compare_semantics(actual, item["expected"])
                except AssertionError:
                    failures.append(f"{item['id']}:semantic_mismatch")
            latency = time.perf_counter() - start
            latencies.append(latency)
            for field in vars(total_metrics):
                value = getattr(total_metrics, field) + getattr(metrics, field)
                setattr(total_metrics, field, value)
            retry_requests += bool(metrics.validation_repairs or metrics.transient_retries)
            for index, expected in enumerate(item["expected"]):
                kind = expected["directive_type"]
                counts[kind] += 1
                counts["total"] += 1
                if index >= len(actual):
                    continue
                observed = actual[index]
                type_ok = (
                    observed.get("note_index") == expected["note_index"]
                    and observed.get("applies") is expected["applies"]
                    and observed.get("directive_type") == kind
                )
                hours_ok = _hours(observed) == _hours(expected)
                number_ok = _equal_number(_numeric(observed), _numeric(expected))
                correct["type"] += type_ok
                if expected["structured_adjustment"] is not None:
                    correct["hours"] += hours_ok
                if _numeric(expected) is not None:
                    correct["numeric"] += number_ok
                if type_ok and hours_ok and number_ok:
                    correct[kind] += 1
                    correct["total"] += 1
            print(
                f"{item['id']}: elapsed={latency:.3f}s calls={metrics.provider_calls} "
                f"repairs={metrics.validation_repairs}",
                flush=True,
            )
            if (
                metrics.client_failures
                or metrics.rate_limit_failures
                or metrics.server_failures
                or metrics.transport_failures
            ):
                # One persistent provider error is enough; never burn the remaining suite.
                break
            if position + 1 < len(requests) and pace_seconds:
                await asyncio.sleep(pace_seconds)

    ordered = sorted(latencies)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    numeric_count = sum(
        counts[k] for k in ("solar_reduction", "minimum_battery_reserve", "max_grid_window")
    )
    result = {
        "requests": len(latencies),
        "planned_requests": len(requests),
        "unattempted_requests": len(requests) - len(latencies),
        "notes": counts["total"],
        "correct_notes": correct["total"],
        "accuracy_percent": round(100 * correct["total"] / counts["total"], 2),
        "per_directive": {
            kind: {"correct": correct[kind], "total": counts[kind]}
            for kind in (
                "solar_reduction",
                "minimum_battery_reserve",
                "no_charge_window",
                "no_discharge_window",
                "max_grid_window",
                "no_op",
            )
        },
        "type_accuracy_percent": round(100 * correct["type"] / counts["total"], 2),
        "time_window_accuracy_percent": (
            round(100 * correct["hours"] / (counts["total"] - counts["no_op"]), 2)
            if counts["total"] > counts["no_op"]
            else None
        ),
        "numeric_accuracy_percent": (
            round(100 * correct["numeric"] / numeric_count, 2) if numeric_count else None
        ),
        "no_op_accuracy_percent": (
            round(100 * correct["no_op"] / counts["no_op"], 2) if counts["no_op"] else None
        ),
        "latency_seconds": {
            "p50": round(statistics.median(latencies), 3),
            "p95": round(p95, 3),
            "max": round(max(latencies), 3),
        },
        "provider_calls": total_metrics.provider_calls,
        "transient_retries": total_metrics.transient_retries,
        "validation_repairs": total_metrics.validation_repairs,
        "invalid_outputs": total_metrics.invalid_outputs,
        "retry_request_rate_percent": round(100 * retry_requests / len(latencies), 2),
        "invalid_output_rate_per_call_percent": (
            round(100 * total_metrics.invalid_outputs / total_metrics.provider_calls, 2)
            if total_metrics.provider_calls
            else 0
        ),
        "prompt_tokens": total_metrics.prompt_tokens,
        "completion_tokens": total_metrics.completion_tokens,
        "rate_limit_failures": total_metrics.rate_limit_failures,
        "server_failures": total_metrics.server_failures,
        "client_failures": total_metrics.client_failures,
        "transport_failures": total_metrics.transport_failures,
        "failures": failures,
    }
    passed = (
        len(latencies) == len(requests) and correct["total"] == counts["total"] and not failures
    )
    return result, passed


async def main(args: argparse.Namespace) -> int:
    try:
        settings = Settings.from_env()
    except ValueError:
        print("Invalid LLM configuration; check environment variable names and types.")
        return 2
    if not settings.configured:
        print("Live benchmark requires LLM_API_KEY (environment or ignored .env).")
        return 2
    try:
        result, passed = await benchmark(settings, args.pace_seconds, set(args.request))
    except ValueError:
        print("Invalid request selection or pacing; use --help.")
        return 2
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", action="append", default=[], help="run one request ID")
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=7.5,
        help="delay between calls for Groq free-tier token limits (default: 7.5)",
    )
    raise SystemExit(asyncio.run(main(parser.parse_args())))
