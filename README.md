# GridWise — BUP CSE FEST 2026 preliminary

A Python 3.12 backend for the 24-hour campus energy challenge. It interprets all operator notes with a language model, validates their structured directives, and minimizes grid electricity cost with a deterministic linear program. No frontend, authentication, or sample-specific production logic is present.

## Organizer files (kept locally)

`data/` is ignored by Git. The organizer PDFs and public sample JSON are supplied separately and are not included in new clones. Neither PDF explicitly requires committing those original files. The guide does require reproducible public-sample testing, so restore the JSON before running the public-case commands below. Run these commands from the repository root after cloning:

```bash
mkdir -p data
# Set this to the location of your downloaded organizer document pack.
organizer_docs="$HOME/Downloads/BUP_CSE_FEST_2026_Participant_Docs"
cp "$organizer_docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json" data/
```

The PDFs may also be kept in `data/` for reference; neither the API nor tests read them. General tests and socket smoke tests work without organizer files. If the JSON is absent, pytest explicitly skips the public-case module and the public-case runner exits with setup instructions; it never reports those cases as passed. To verify all ten official cases, restore the unmodified JSON first.

## Quickstart from a fresh clone

Prerequisites: Python 3.12 with `venv`, or Docker. For real interpretation you need a reachable OpenAI-compatible Chat Completions provider, a model with JSON output support, and sufficient quota.

```bash
git clone https://github.com/Shashwata2004/BUP_HT.git
cd BUP_HT
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env: set LLM_API_KEY and LLM_MODEL; set LLM_BASE_URL for another provider.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
```

The repository remains private during the event; cloning requires authorized repository access. `.env` is loaded locally without overriding exported environment variables. The Docker image receives configuration at runtime. No API key is supplied in this repository.

In a second terminal:

```bash
source .venv/bin/activate
curl --fail-with-body http://127.0.0.1:8000/health
# Expected HTTP 200: {"status":"ok"}

# Extract an unchanged organizer request; this is validation tooling, not production logic.
mkdir -p .artifacts
python - <<'PY'
import json
from pathlib import Path
cases = json.loads(Path('data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json').read_text())
Path('.artifacts/request.json').write_text(json.dumps(cases['cases'][0]['input']))
PY
curl --fail-with-body http://127.0.0.1:8000/optimize-energy \
  -H 'Content-Type: application/json' --data-binary @.artifacts/request.json
python scripts/run_public_cases.py
```

A successful response contains exactly `scenario_id`, `directive_interpretation`, `hourly_plan`, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, and `plan_summary`. Each of the 24 plan entries has `hour`, `grid_kwh`, `solar_used_kwh`, `battery_action`, `battery_kwh`, and `battery_energy_after_kwh`. Full request/response examples, including all required fields, are in the organizer-supplied `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`; copy it into `data/` using the instructions above.

`GET /health` returns `{"status":"ok"}` only after configuration is present and the solver has initialized. Missing/invalid configuration returns a controlled HTTP 500 `not_ready`. Health does not make a paid model call and does not certify current provider quota or credentials; verify those with a real POST before submission.

`POST /optimize-energy` returns HTTP 400 for malformed JSON or invalid request shape/values. Model failures, timeouts, unavailable solutions, or replay failures return controlled HTTP 500 JSON error codes. These responses omit input values, provider response bodies, credentials, and tracebacks. Valid organizer cases are specified to be feasible.

## Architecture

```text
request → strict Pydantic validation → one batched LLM interpretation
        → deterministic directive guardrails → directive application
        → SciPy/HiGHS linear program → independent replay → JSON response
```

- `app/models.py`: exact request, discriminated directive, and response models; finite nonnegative numbers; strict types; unknown keys rejected. Request hours may arrive in any order and are sorted after checking coverage. Responses always use hours 0–23 in order.
- `app/interpreter.py`: real asynchronous HTTP adapter to `/chat/completions`. Sends only the notes and battery capacity. Temperature is zero by default. Operator notes are explicitly **untrusted data** and cannot change the system prompt, schema, supported operations, or application behavior. There is no regex interpreter or deterministic semantic fallback.
- `app/guardrails.py`: validates exact adjustment shapes, note coverage/order, booleans, enum values, sorted unique integer hours, solar fractions, reserve bounds, grid caps, duplicate JSON keys, and finite values. A bad model output gets at most one repair with controlled validation feedback. Provider transport/auth/rate-limit errors are not retried. There are never more than two model calls per request.
- `app/optimizer.py`: applies the directives and solves the scheduling problem. The LLM never performs scheduling. Signed battery flow is positive for charging and negative for discharging, so simultaneous charge/discharge is impossible.
- `app/validator.py`: independently reconstructs effective solar and active constraints from the original scenario and directives, replays all state transitions, checks energy balance and final neutrality, and recalculates aggregates. It does not use the optimizer's constraint arrays. No successful response bypasses replay.
- `app/main.py`: lifespan-managed HTTP connection pool and a dedicated solver thread. LLM calls can overlap while the tiny LPs are serialized to avoid thread proliferation. Exceptions and logs are sanitized.

The model is mandatory because hidden notes may paraphrase operational restrictions. Deterministic code validates the extracted representation but cannot establish semantic correctness by itself. Live tests are needed to measure the chosen model's language accuracy.

## Mathematical model

For each hour `h`, solve for grid `g[h]`, used solar `s[h]`, signed battery flow `f[h]`, and post-hour energy `E[h]`:

```text
minimize Σ tariff[h] * g[h]
g[h] + s[h] - f[h] = demand[h]
E[h] = E[h-1] + f[h]                 (E[-1] = initial energy)
0 <= g[h] <= active grid cap         (no upper cap unless directed)
0 <= s[h] <= effective solar[h]
-max_discharge <= f[h] <= max_charge
active reserve[h] <= E[h] <= capacity
E[23] = initial energy
```

No-charge sets the flow upper bound to zero. No-discharge sets its lower bound to zero. Overlapping reserve constraints take the maximum; overlapping grid caps take the minimum. Solar can be curtailed; grid export is prohibited. There are 96 continuous variables and 49 equality constraints, with no greedy approximation, integer search, or cost perturbation. HiGHS must report an optimal result. Internal values are not rounded; aggregates use `math.fsum`. Replay uses an absolute `1e-6` tolerance, stricter than the organizer's `0.01` kWh/BDT tolerance.

Supported interpretations are `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, and `no_op`. Exactly one interpretation corresponds to each of the 1–3 notes. Only `no_op` uses `applies=false` and a null adjustment. Windows are start-inclusive/end-exclusive. Solar factors mean the usable fraction remaining; a reduction **by** 80% leaves 0.2. Percentage reserves are converted by the model into absolute kWh using capacity. Reserve limits apply to energy **after** the affected hour.

## Model and environment configuration

There is no hard-coded model identifier. The actual provider/model are selected exclusively by deployment configuration; no live model has yet been selected or verified for this baseline. Use a low-latency language model that supports the configured protocol and output mode. The default API root is OpenAI's compatible endpoint; other hosted or locally served compatible models can be selected with `LLM_BASE_URL`.

| Variable | Requirement/default |
| --- | --- |
| `LLM_API_KEY` | Required. Provider credential; for an unauthenticated local server, use a non-secret placeholder accepted by that server. |
| `LLM_MODEL` | Required. Exact model identifier available at your provider. |
| `LLM_BASE_URL` | Optional; `https://api.openai.com/v1`. Include the API root (usually `/v1`), not `/chat/completions`. No embedded credentials/query string. |
| `LLM_TIMEOUT_SECONDS` | 10 seconds per model attempt; must be >0 and ≤12. Covers total wall time, including a slow response stream. |
| `REQUEST_TIMEOUT_SECONDS` | 27 seconds for the pipeline; must be >0 and ≤28. Leaves margin below the judge's 30-second limit. |
| `LLM_RESPONSE_FORMAT` | `json_schema` by default with strict schema. Use `json_object` or `text` only when the provider lacks stricter support; validation always applies. |
| `LLM_TEMPERATURE` | `0` by default; other numeric values are rejected. `omit` is available for models that forbid this field; choose an appropriate deterministic provider mode. |
| `LLM_MAX_TOKENS` | 1600 by default; allowed range 256–8192. Includes all note interpretations, not a plan. |
| `LLM_TOKEN_PARAMETER` | `max_tokens` by default; set `max_completion_tokens` if required by the provider. |
| `RUN_LIVE_LLM` | Test-only explicit opt-in (`1`) to enable live pytest cases. Normal pytest never calls a paid model. |

Docker also sets `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, and `PIP_NO_CACHE_DIR=1` as runtime/build defaults. No additional application configuration is required. The service port is 8000; use Docker port mapping or uvicorn's `--port` to change the external port.

The adapter uses [strict structured output](https://developers.openai.com/api/docs/guides/structured-outputs) with nested `anyOf` schemas where supported. Provider capability differences are explicit configuration, not automatic retries that might exceed the latency budget. The linear solver is [SciPy's HiGHS interface](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs.html); models use [Pydantic strict validation](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/).

## Tests and public sample verification

```bash
source .venv/bin/activate
pytest -q
ruff check app tests scripts
python -m compileall -q app tests scripts
python scripts/run_public_cases.py --offline
python scripts/smoke_test.py
```

General offline tests use an independently constructed synthetic fixture and cover the exact schemas, all directive types, no-op, malformed output and repair, provider failures, prompt isolation, percentage/time output handling, battery transitions, rates, reserves, energy balance, neutrality, solar/grid restrictions, simultaneous directives, corrupted plans, safe errors, and 50 seeded scenarios checked against an independent exhaustive battery-state dynamic program. Mocked normalization tests check the adapter/guardrail path; they do **not** prove real-model language understanding.

`--offline` reads the expected interpretation from each organizer case, passes it through our guardrails and optimizer, independently replays the plan, and compares cost against the organizer optimum within 0.01 BDT. **Expected result: 10/10**, with zero cost difference on the current baseline. Equivalent optimal action sequences are accepted. The official files remain unchanged in local, Git-ignored `data/`; production modules never read them, and the Docker image excludes them. Public wording, IDs, numeric values, and reference schedules are not hard-coded in application logic.

Real-provider checks (incur provider usage):

```bash
# Direct interpreter → optimizer path; requires configured .env/environment.
python scripts/run_public_cases.py --live

# All cases against a running local service or a deployed API.
python scripts/run_public_cases.py
python scripts/run_public_cases.py --url https://YOUR-DEPLOYED-HOST

# Optional pytest E2E tests, skipped unless explicitly enabled and configured.
RUN_LIVE_LLM=1 pytest -q -m live
```

The runner checks interpretation semantics, ignores explanation wording, replays against both reported directives and organizer ground truth, validates schema/aggregates, compares cost, and reports request timing. Full score latency requires p95 ≤5 seconds; ≤15 seconds earns partial latency credit. Optimizer-only timing is not an LLM/API latency claim.

`smoke_test.py` starts actual uvicorn processes, a clearly isolated mock model provider, and verifies health plus 24 POSTs using eight concurrent clients. It makes no paid calls and shuts down its processes. The mock provider lives under `tests/` and cannot be enabled in the production image.

## Docker fallback

```bash
docker build -t gridwise:prompt-01 .
docker run --rm --name gridwise -p 8000:8000 --env-file .env gridwise:prompt-01
curl --fail-with-body http://127.0.0.1:8000/health
python scripts/run_public_cases.py

# Reproducible isolated health + POST smoke check without real model credentials:
python scripts/smoke_test.py --docker-image gridwise:prompt-01
```

The image binds to `0.0.0.0:8000`, runs as non-root UID 10001, has a healthcheck, and uses pinned runtime dependencies. The Docker context is allowlisted to application code, requirements, and Dockerfile; it excludes `.env`, tests, samples, PDFs, Git, caches, and credentials. The base image has an exact Python patch tag. For final submission, additionally pin the published image by digest.

A registry image has **not** been pushed in this phase. Once the intended registry is configured and publication is authorized, tag/push the tested image and replace the placeholders below with the actual pullable reference and exact digest:

```bash
docker pull REGISTRY/OWNER/gridwise@sha256:ACTUAL_DIGEST
docker run --rm -p 8000:8000 --env-file .env REGISTRY/OWNER/gridwise@sha256:ACTUAL_DIGEST
```

These placeholder pull commands are a submission template, not a claim that a registry artifact exists. Keep the final image pullable throughout evaluation and verify the hosted API from outside the development network.

## Reproducibility, security, and limitations

- `requirements.txt` pins runtime and transitive versions; `requirements-dev.txt` pins the tested developer environment. `requirements.in` records direct runtime dependencies. Python, FastAPI, Pydantic, HTTPX, NumPy, SciPy/HiGHS, uvicorn, python-dotenv, pytest, and Ruff are credited external dependencies. OpenAI Codex assisted implementation; no external project solution was copied.
- No secrets are embedded, committed, logged, or returned. Keys are read through a secret-valued configuration field. HTTPX URL logging is disabled, redirects are not followed, and provider failures expose only stable application error codes. The public judge endpoints have no authentication as required; protect deployment account credentials separately.
- Provider availability, quota, schema compatibility, semantic accuracy, and live p95 must be verified after selecting the model. There is no fallback that silently converts failed interpretations to no-op. An unavailable or invalid model result safely fails the request.
- The canonical statement does not define overlapping solar-reduction precedence. We apply notes in order, each assigning `original_solar * factor` exactly as its equation states. This is a documented assumption; obtain organizer clarification before relying on overlapping solar cases. Repeated reserve/grid restrictions combine by max/min. Explicit overnight windows use sorted hours within the cyclic day; ambiguous or unsupported note semantics remain a model risk.
- Zero capacity/rates, zero tariff/demand, excess solar, reversed input-hour order, and infeasible scenarios are tested. Extremely ill-conditioned values may lead to controlled solver/replay failure rather than a misleading successful plan. No arbitrary upper bound is imposed on otherwise finite scenario numbers.
- One optimal schedule is returned. Cost ties may have different action sequences across solver releases; exact pinned builds are reproducible, and the official judge accepts equivalent optima.
- The backend and local Docker image are the deliverables for this phase. Public hosting, published registry reference, final provider selection, externally verified endpoint, and the required ≤3-minute video remain submission work. Keep the repository private during the event; visibility changes require a later explicit user instruction.

See [acceptance criteria](docs/acceptance.md) for the extracted contract/rubric and [verification record](docs/verification.md) for commands and measured baseline results.
