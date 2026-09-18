#!/usr/bin/env python3
"""Exercise local/Docker sockets; mock by default, one real call only with --live."""

import argparse
import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.models import OptimizationResponse, Scenario  # noqa: E402
from app.validator import validate_plan  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def wait_ready(url: str, processes: list[subprocess.Popen]) -> None:
    deadline = time.monotonic() + 30
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError("smoke-test server exited before readiness")
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise RuntimeError("smoke-test readiness timeout")


def run(image: str | None, live: bool = False) -> None:
    configuration = Settings.from_env() if live else None
    if configuration is not None and not configuration.configured:
        raise RuntimeError("Live smoke requires LLM_API_KEY in the environment or ignored .env")
    provider_port, api_port = free_port(), free_port()
    scenario = Scenario.model_validate(
        {
            "scenario_id": "socket-smoke",
            "operator_notes": ["The chess club meets next month."],
            "hours": [
                {
                    "hour": h,
                    "demand_kwh": 10,
                    "solar_kwh": 4 if 7 <= h < 17 else 0,
                    "tariff_bdt_per_kwh": 2 if h < 12 else 5,
                }
                for h in range(24)
            ],
            "battery": {
                "capacity_kwh": 12,
                "initial_energy_kwh": 6,
                "minimum_energy_kwh": 2,
                "max_charge_kwh_per_hour": 3,
                "max_discharge_kwh_per_hour": 3,
            },
        }
    )
    with ExitStack() as stack:
        processes = []
        # Use only explicitly resolved app settings. Docker receives values via its child
        # environment, never secret-bearing command arguments or image layers.
        if configuration is not None:
            service_env = {
                name.upper(): str(value)
                for name, value in configuration.model_dump().items()
                if name != "llm_api_key" and value is not None
            }
            service_env["LLM_API_KEY"] = configuration.llm_api_key.get_secret_value()
            if configuration.llm_temperature is None:
                service_env["LLM_TEMPERATURE"] = "omit"
        else:
            provider = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "tests.mock_provider:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    str(provider_port),
                    "--no-access-log",
                    "--log-level",
                    "error",
                ],
                cwd=ROOT,
            )
            stack.callback(stop, provider)
            processes.append(provider)
            wait_ready(f"http://127.0.0.1:{provider_port}/openapi.json", processes)
            provider_host = "host.docker.internal" if image else "127.0.0.1"
            service_env = {
                "LLM_API_KEY": "smoke-placeholder",
                "LLM_MODEL": "smoke-mock",
                "LLM_BASE_URL": f"http://{provider_host}:{provider_port}/v1",
            }
        child_env = {**os.environ, **service_env}
        if image:
            name = f"gridwise-smoke-{os.getpid()}"
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    name,
                    "--add-host",
                    "host.docker.internal:host-gateway",
                    "-p",
                    f"127.0.0.1:{api_port}:8000",
                    *(argument for name in service_env for argument in ("-e", name)),
                    image,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                env=child_env,
            )
            stack.callback(
                subprocess.run, ["docker", "stop", name], stdout=subprocess.DEVNULL, check=False
            )
        else:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--no-access-log",
                    "--log-level",
                    "error",
                ],
                cwd=ROOT,
                env=child_env,
            )
            stack.callback(stop, server)
            processes.append(server)
        base = f"http://127.0.0.1:{api_port}"
        wait_ready(base + "/health", processes)
        with httpx.Client(trust_env=False, timeout=30) as client:
            assert client.get(base + "/health").json() == {"status": "ok"}

            def request_one(_):
                start = time.perf_counter()
                result = client.post(base + "/optimize-energy", json=scenario.model_dump())
                result.raise_for_status()
                response = OptimizationResponse.model_validate(result.json())
                validate_plan(scenario, response)
                assert response.directive_interpretation[0].directive_type == "no_op"
                return time.perf_counter() - start

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                times = list(pool.map(request_one, range(1 if live else 24)))
            print(
                json.dumps(
                    {
                        "mode": "docker" if image else "local",
                        "health": "ok",
                        "valid_posts": len(times),
                        "max_seconds": round(max(times), 4),
                        "provider": "live configured LLM"
                        if live
                        else "mock; language accuracy NOT tested",
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-image", help="test this local Docker image instead of local API")
    parser.add_argument("--live", action="store_true", help="make one real LLM call (uses quota)")
    args = parser.parse_args()
    try:
        run(args.docker_image, args.live)
    except Exception as exc:
        print(f"Smoke failed: {type(exc).__name__}; check configuration and service availability.")
        raise SystemExit(1) from None
