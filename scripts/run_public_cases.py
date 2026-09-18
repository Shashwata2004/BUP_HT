#!/usr/bin/env python3
"""Official fixtures are read only by validation tooling, never by production code."""

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.guardrails import validate_directives  # noqa: E402
from app.interpreter import InterpretationMetrics, LLMInterpreter  # noqa: E402
from app.models import OptimizationResponse, Scenario  # noqa: E402
from app.optimizer import optimize  # noqa: E402
from app.validator import validate_plan  # noqa: E402

SAMPLES = ROOT / "data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def load_cases() -> list[dict]:
    return json.loads(SAMPLES.read_text())["cases"]


def compare_semantics(actual: list, expected: list) -> None:
    def equivalent(a, b):
        if type(a) in (int, float) and type(b) in (int, float):
            return math.isclose(a, b, rel_tol=0, abs_tol=0.01)
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b, strict=True))
        return type(a) is type(b) and a == b

    a = [{k: v for k, v in d.items() if k != "explanation"} for d in actual]
    b = [{k: v for k, v in d.items() if k != "explanation"} for d in expected]
    if not equivalent(a, b):
        raise AssertionError("directive semantics differ from official reference")


def verify_case(case: dict, response: OptimizationResponse) -> float:
    scenario = Scenario.model_validate(case["input"])
    compare_semantics(
        [d.model_dump() for d in response.directive_interpretation],
        case["expected_output"]["directive_interpretation"],
    )
    validate_plan(scenario, response, tolerance=0.01)
    # Replay once more with organizer ground truth, never only self-reported constraints.
    truth = validate_directives(
        {"directive_interpretation": case["expected_output"]["directive_interpretation"]}, scenario
    )
    validate_plan(
        scenario, response.model_copy(update={"directive_interpretation": truth}), tolerance=0.01
    )
    delta = response.total_cost_bdt - case["expected_output"]["total_cost_bdt"]
    if abs(delta) > 0.01:
        raise AssertionError(f"cost differs from official optimum by {delta:.8f} BDT")
    return delta


async def run(args: argparse.Namespace) -> int:
    if not SAMPLES.is_file():
        print(
            "Organizer sample pack missing. Copy "
            "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json into data/ "
            "as described in README.md."
        )
        return 2
    if not math.isfinite(args.pace_seconds) or not 0 <= args.pace_seconds <= 60:
        print("--pace-seconds must be finite and between 0 and 60.")
        return 2
    try:
        settings = Settings.from_env() if args.live else None
    except ValueError:
        print("Invalid LLM configuration; check environment variable names and types.")
        return 2
    if settings is not None and not settings.configured:
        print("Live mode requires LLM_API_KEY and LLM_MODEL (environment or .env).")
        return 2
    passed = 0
    latencies = []
    attempted = 0
    total_metrics = InterpretationMetrics()
    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case["id"] in args.case]
        if len(cases) != len(args.case):
            print("Unknown or duplicate --case value.")
            return 2
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for position, case in enumerate(cases):
            attempted += 1
            metrics = InterpretationMetrics()
            start = time.perf_counter()
            try:
                scenario = Scenario.model_validate(case["input"])
                if args.offline:
                    directives = validate_directives(
                        {
                            "directive_interpretation": case["expected_output"][
                                "directive_interpretation"
                            ]
                        },
                        scenario,
                    )
                    response = optimize(scenario, directives)
                elif args.live:
                    directives = await LLMInterpreter(settings, client).interpret(scenario, metrics)
                    response = optimize(scenario, directives)
                else:
                    result = await client.post(
                        args.url.rstrip("/") + "/optimize-energy", json=case["input"]
                    )
                    result.raise_for_status()
                    response = OptimizationResponse.model_validate(result.json())
                delta = verify_case(case, response)
                elapsed = time.perf_counter() - start
                print(
                    f"PASS {case['id']}: cost={response.total_cost_bdt:.6f} "
                    f"delta={delta:+.8f} BDT elapsed={elapsed:.3f}s",
                    flush=True,
                )
                passed += 1
            except Exception as exc:
                # Safe type only: provider URLs/bodies may contain credentials.
                print(f"FAIL {case['id']}: {type(exc).__name__}")
            finally:
                latencies.append(time.perf_counter() - start)
                if args.live:
                    for field in vars(total_metrics):
                        value = getattr(total_metrics, field) + getattr(metrics, field)
                        setattr(total_metrics, field, value)
            if (
                metrics.client_failures
                or metrics.rate_limit_failures
                or metrics.server_failures
                or metrics.transport_failures
            ):
                print("Provider failed; remaining cases were not attempted.")
                break
            if not args.offline and position + 1 < len(cases) and args.pace_seconds:
                await asyncio.sleep(args.pace_seconds)
    print(f"{passed}/{len(cases)} passed")
    if attempted != len(cases):
        print(f"{len(cases) - attempted} cases not attempted")
    if latencies:
        p95 = sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1]
        print(
            f"Latency over {len(latencies)} attempted cases: "
            f"p50={statistics.median(latencies):.3f}s p95={p95:.3f}s "
            f"max={max(latencies):.3f}s"
        )
    if args.live:
        print(
            f"Provider calls={total_metrics.provider_calls} "
            f"transient retries={total_metrics.transient_retries} "
            f"validation repairs={total_metrics.validation_repairs} "
            f"invalid outputs={total_metrics.invalid_outputs} "
            f"prompt tokens={total_metrics.prompt_tokens} "
            f"completion tokens={total_metrics.completion_tokens} "
            f"rate-limit failures={total_metrics.rate_limit_failures} "
            f"server failures={total_metrics.server_failures} "
            f"client failures={total_metrics.client_failures} "
            f"transport failures={total_metrics.transport_failures}"
        )
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--offline", action="store_true", help="use official expected directives")
    modes.add_argument("--live", action="store_true", help="call configured LLM directly")
    parser.add_argument("--case", action="append", help="run only this case ID; repeat as needed")
    parser.add_argument(
        "--pace-seconds",
        type=float,
        default=7.5,
        help="delay between direct live calls for Groq free-tier token limits (default: 7.5)",
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8000", help="API base URL (default mode)"
    )
    raise SystemExit(asyncio.run(run(parser.parse_args())))
