import asyncio
import logging
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from scipy.optimize import linprog

from app.config import Settings
from app.errors import GuardrailError, InterpretationError, OptimizationError, ReplayError
from app.interpreter import LLMInterpreter
from app.models import OptimizationResponse, Scenario
from app.optimizer import optimize

logger = logging.getLogger("gridwise")


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.ready = False
        try:
            configuration = settings or Settings.from_env()
        except (ValueError, ValidationError):
            # No raw settings validation: it may contain credentials.
            logger.error("Invalid service configuration")
            yield
            return
        # HTTPX request logs may contain a sensitive provider URL. Keep them disabled.
        logging.getLogger("httpx").disabled = True
        logging.getLogger("httpcore").disabled = True
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            application.state.settings = configuration
            application.state.interpreter = LLMInterpreter(configuration, client)
            # One solver thread avoids HiGHS oversubscription under concurrent requests.
            # Model HTTP calls remain concurrent; 24-hour LPs take only milliseconds.
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="gridwise-solver") as solver:
                application.state.solver = solver
                loop = asyncio.get_running_loop()
                warmup = await loop.run_in_executor(solver, linprog, [1.0])
                application.state.ready = bool(configuration.configured and warmup.success)
                yield
                application.state.ready = False

    application = FastAPI(
        title="GridWise", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo request input (notes may themselves contain sensitive text).
        return JSONResponse(status_code=400, content={"error": "invalid_request"})

    @application.get("/health")
    async def health(request: Request) -> JSONResponse:
        if not getattr(request.app.state, "ready", False):
            return JSONResponse(status_code=500, content={"error": "not_ready"})
        return JSONResponse(content={"status": "ok"})

    @application.post("/optimize-energy", response_model=OptimizationResponse)
    async def optimize_energy(
        scenario: Scenario, request: Request
    ) -> OptimizationResponse | JSONResponse:
        if not getattr(request.app.state, "ready", False):
            return JSONResponse(status_code=500, content={"error": "not_ready"})
        try:
            async with asyncio.timeout(request.app.state.settings.request_timeout_seconds):
                directives = await request.app.state.interpreter.interpret(scenario)
                return await asyncio.get_running_loop().run_in_executor(
                    request.app.state.solver, optimize, scenario, directives
                )
        except InterpretationError:
            return JSONResponse(status_code=500, content={"error": "interpretation_unavailable"})
        except OptimizationError:
            return JSONResponse(status_code=500, content={"error": "optimization_unavailable"})
        except TimeoutError:
            return JSONResponse(status_code=500, content={"error": "request_timeout"})
        except (GuardrailError, ReplayError, ValidationError):
            logger.error("Deterministic pipeline validation rejected a result")
            return JSONResponse(status_code=500, content={"error": "validation_failed"})
        except Exception:
            # Never allow an unexpected exception to reach uvicorn with raw provider details.
            logger.error("Unexpected optimization failure")
            return JSONResponse(status_code=500, content={"error": "internal_error"})

    return application


app = create_app()
