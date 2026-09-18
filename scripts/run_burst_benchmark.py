#!/usr/bin/env python3
"""Explicit two-request real-provider burst; no retries outside the production adapter."""

import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.interpreter import InterpretationMetrics, LLMInterpreter  # noqa: E402
from app.optimizer import optimize  # noqa: E402
from scripts.run_live_benchmark import make_scenario  # noqa: E402
from scripts.run_public_cases import compare_semantics  # noqa: E402


async def benchmark(settings: Settings) -> tuple[dict, bool]:
    suite = json.loads((ROOT / "tests/data/semantic_hidden_style_cases.json").read_text())
    statuses: Counter[int] = Counter()

    async def record(response):
        statuses[response.status_code] += 1

    async with httpx.AsyncClient(
        trust_env=False, follow_redirects=False, event_hooks={"response": [record]}
    ) as client:
        interpreter = LLMInterpreter(settings, client)
        with ThreadPoolExecutor(max_workers=1) as solver:

            async def one(item):
                metrics = InterpretationMetrics()
                start = time.perf_counter()
                success = False
                try:
                    scenario = make_scenario(item, suite["battery_capacity_kwh"])
                    directives = await interpreter.interpret(scenario, metrics)
                    compare_semantics([d.model_dump() for d in directives], item["expected"])
                    await asyncio.get_running_loop().run_in_executor(
                        solver, optimize, scenario, directives
                    )
                    success = True
                except Exception:
                    pass  # aggregate counters only; never print a provider body or exception
                return success, time.perf_counter() - start, metrics

            results = await asyncio.gather(*(one(item) for item in suite["requests"][:2]))
    latencies = [r[1] for r in results]
    successes = sum(r[0] for r in results)
    return {
        "requests": 2,
        "successes": successes,
        "p50_seconds": round(statistics.median(latencies), 3),
        "p95_seconds": round(max(latencies), 3),
        "max_seconds": round(max(latencies), 3),
        "provider_429_responses": statuses[429],
        "provider_5xx_responses": sum(n for status, n in statuses.items() if status >= 500),
        "provider_calls": sum(r[2].provider_calls for r in results),
        "transient_retries": sum(r[2].transient_retries for r in results),
        "validation_repairs": sum(r[2].validation_repairs for r in results),
    }, successes == 2


if __name__ == "__main__":
    try:
        settings = Settings.from_env()
        if not settings.configured:
            raise ValueError("missing local configuration")
        result, passed = asyncio.run(benchmark(settings))
    except Exception:
        print("Burst benchmark unavailable; check local configuration. No credentials logged.")
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if passed else 1)
