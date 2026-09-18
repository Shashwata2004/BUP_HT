# Live Groq verification

Verified on 2026-09-18. These results measure this local environment and account, not hidden judge performance or burst capacity. The optimizer, replay validator, public API schemas, endpoints, and solver dependencies were preserved.

## Current submission state

- Offline suite: **1,592 passed**, 12 explicitly skipped live tests, one unchanged upstream warning.
- Final semantic red team: **54/54 notes** across 18 requests, with 100% type, time-window, numeric, and no-op accuracy; zero retries, repairs, invalid outputs, or provider failures; p50 1.832 seconds and p95/max 2.739 seconds.
- Public Render API: `https://bup-ht.onrender.com`; exact `/health` response and a real Groq-backed POST reverified on 2026-09-18.
- Deployed official cases: **10/10**, exact organizer-optimal costs; p50 1.471 seconds and p95/max 2.017 seconds.
- GHCR fallback: `ghcr.io/shashwata2004/bup_ht@sha256:fb6d6d3e5e65520368e317f34716b4c7facdf2fdbca3a7be03f011e8af1cd318`; remote pull, health, and real Groq POST passed. Package visibility remains private until the post-deadline publication step.
- Source repository remains private during the event as required.

## Hidden-case stress work: scope and findings

That verification round kept the existing solver, replay validator, API contract, provider adapter, dependency pins and all previous tests. The offline baseline was 291 passed / 11 live tests skipped. New coverage included 1,000 fixed-seed feasible numeric scenarios, 35 overlapping directive combinations, 10 named independent optimality checks, 24 decimal-scaled oracle checks, systematic API fuzzing, and concurrent failure recovery. At the end of that round, the offline suite passed **1,539 tests**, with 11 explicitly opted-out live tests and one upstream Starlette/AnyIO deprecation warning. The current count is recorded above.

The independently authored semantic dataset is `tests/data/semantic_hidden_style_cases.json`: **150 notes, 50 three-note requests, 25 notes per category**. It has 24 requests tagged for time boundaries, 10 adversarial requests (30 notes), and two requests with long irrelevant context. Production never reads the dataset.

The initial 48-request core run scored 142/144 notes. A diagnostic rerun reproduced both differences. One was a real temporal defect: a tomorrow-only grid limit was applied today. The other exposed an ambiguous test sentence about unavailable **forecast** information. That sentence was changed to unambiguously describe unavailable **generation**; the original ambiguity is not counted as a proven application bug. The generic prompt now resolves the stated day before interpreting restrictions and explicitly includes factor zero for total solar unavailability. It contains no fixture wording, IDs, values or per-case branches.

A focused 4-request run passed 12/12 notes, including both diagnostic requests and the two long-context requests. The subsequent 50-request run passed 150/150 with all type, affected-hour, numeric and no-op comparisons correct. Each category scored 25/25. It used 50 calls, zero transient retries, zero validation repairs, zero malformed outputs and zero provider failures. Prompt/completion usage was 52,441 / 24,255 tokens. Latency was **p50 1.766 s, p95 2.896 s, maximum 5.852 s**. The one maximum above five seconds did not push p95 over the full-score threshold.

That full run had loaded the dataset before the forecast/generation wording clarification was saved. The clarified request was verified separately: **3/3 notes correct**, one call, no retries/repairs, 2.136 seconds. Thus every note in the final fixture has been exercised live; the original batch latency above is kept separate rather than silently replacing a measurement. No failures remain on the final fixture.

These live runs pause ten seconds between requests, excluded from latency. Production requests have no artificial pacing. Every successful synthetic result passes guardrails, optimization and replay against the intended directives; no benchmark treats mocked output as evidence of language accuracy. Semantic mismatch reports now record only validated index/type/adjustment fields, excluding notes, explanations and raw provider responses.

### Final public and operational checks

| Check | Measured result |
| --- | --- |
| Official optimizer cases | 10/10; every cost difference exactly 0 BDT |
| Official real Groq cases after prompt change | 10/10; every cost difference exactly 0 BDT |
| Official live latency p50 / p95 / max | 1.445 / 2.081 / 2.081 seconds |
| Official live provider accounting | 10 calls; 0 retries, repairs, invalid outputs or provider failures; 10,054 prompt / 3,163 completion tokens |
| Small real Groq burst | 2/2 simultaneous requests; p50 1.833 s, p95/max 2.094 s |
| Burst response accounting | 2 calls; 0 observed 429 or 5xx responses; 0 retries or repairs |
| Mocked mixed concurrency | 100/100 requests at 16 clients; 1–3 notes and distinct scenarios; ten injected 503s recover in 110 total model calls |
| Local actual sockets, mocked provider | 100/100 at 16 clients; p50 0.0603 s, p95 0.1238 s, max 0.2439 s |
| Final Docker actual sockets, mocked provider | 100/100 at 16 clients; p50 0.0669 s, p95 0.1324 s, max 0.2129 s |
| Local real-provider health + POST | Passed; POST 0.7210 s |
| Final Docker real-provider health + POST | Passed; POST 1.4115 s; key provided only at runtime |
| Randomized optimizer | 1,000/1,000 feasible seeded witnesses and optimized schedules replay; no failures |
| New independent optimality checks | 35 directive combinations + 10 named scenarios + 24 decimal-scaled scenarios; all match the integer-state oracle |
| API fuzz | 102 field mutations + 7 malformed JSON/encoding inputs; controlled 400s, no model/solver calls |
| Final offline suite | 1,592 passed, 12 live skips, one upstream warning |
| Static/dependency checks | Ruff, compileall and pip check pass |

### Clean-room, container and repository verification

A fresh source snapshot was created under ignored `.artifacts/clean-room`, without the original virtualenv, caches, organizer data or credentials. A new Python 3.12 venv installed **only** `requirements-dev.txt` following README. A no-data test run correctly skipped organizer cases. After restoring the unmodified organizer JSON using the documented procedure, the final snapshot passed all 1,539 offline tests and all ten optimum comparisons. Ruff, imports and dependency checks passed there too. The documented Docker build and mock smoke commands also passed from that directory.

A clean-room uvicorn process then received configuration through named environment variables and served exact `/health` plus an official `/optimize-energy` request: valid interpretation, valid replay and exact optimum, 3.785 seconds. `PYTHONPATH` was removed from the child environment; the service used its own new virtualenv and relocated source. No secret was written to its `.env`. Captured startup/shutdown logs were checked for the real key and stack traces. The initial shutdown assertion expected zero; inspection of the pinned Uvicorn implementation showed it intentionally re-raises SIGTERM after lifespan shutdown. The corrected check requires the shutdown-complete log and allows normal signal termination (`-15` for the child process). This was a verification-harness correction, not an application crash.

The final image was rebuilt using `docker build --no-cache -t gridwise:latest .`. Local image ID: `sha256:470cd3c23ed583f7bc7311a8ae85b20561fbf728aed9ebbe3b56f88d961095d4`, size 116,703,306 bytes. It binds to `0.0.0.0:8000`, runs as `gridwise`, and includes no `.env`, tests, organizer data or baked `LLM_API_KEY`. A separate Docker healthcheck/shutdown audit became healthy in 5.76 seconds and stopped gracefully with exit code 0 and secret-free logs. The application archive, image configuration and image history were checked against the actual local key. This artifact was subsequently published to GHCR under the digest recorded in the current submission state.

Repository scans cover candidate source files, staged/unstaged diffs, all Git history, and generated verification reports using the actual local key plus obvious credential patterns. `.env` remains ignored and untracked; `.env.example` is the only tracked environment file. The existing GitHub repository remains private. Organizer originals remain ignored in `data/`; README explains restoration and tests never silently count absent public data as passed.

No account-wide rate-limit capacity is inferred from two concurrent calls. The hosted provider's quota remains an external dependency; larger bursts may safely fail. Numeric Retry-After values are honored only if finite, at most one second, and within the shared deadline. Other values (including HTTP-date headers), exhausted budgets and persistent errors fail safely without a retry storm. Ambiguous day/window wording, overlapping same-type solar reductions, extreme numeric conditioning and arbitrary note lengths remain documented risks in the [risk audit](hidden-test-risk-audit.md).

## Configuration actually tested

| Setting | Value |
| --- | --- |
| Provider/API root | `https://api.groq.com/openai/v1` |
| Model | `openai/gpt-oss-120b` |
| Response mode | Strict `json_schema` |
| Temperature | 0 |
| Reasoning effort | `low` |
| Output budget | 900 `max_completion_tokens` |
| Interpretation deadline | 10 seconds including bounded retries/repair |
| Credential source | Local ignored `.env`; never included here |

The minimal real authentication/model/strict-schema probe succeeded in 0.600 seconds. The original Pydantic directive union was rejected with a multiple-discriminator error. A union of adjustment objects was then rejected because its variants shared required `hours` keys. The working schema uses a single directive object with a uniform adjustment containing `hours` and three nullable numeric slots. All fields are required and unknown properties are forbidden. Normalization removes unused null slots (or produces official `no_op` null) without inferring semantic values. Conflicting non-null slots are rejected; all official type/applies/hour/range/capacity rules are validated afterwards.

Groq documents [strict schema output](https://console.groq.com/docs/structured-outputs), [reasoning effort](https://console.groq.com/docs/reasoning), and [rate-limit headers](https://console.groq.com/docs/rate-limits). The tested behavior above was established with real responses, not assumed from documentation.

## Earlier baseline complete live runs

| Metric | Official public cases | Independent synthetic suite |
| --- | ---: | ---: |
| Requests | 10 | 16 |
| Passed | 10/10 | 16/16 |
| Correct synthetic notes | — | 48/48 |
| Provider calls | 10 | 16 |
| Transient retries | 0 | 0 |
| Validation repairs | 0 | 0 |
| Provider failures | 0 | 0 |
| p50 | 1.411 s | 1.812 s |
| p95 (nearest rank) | 2.090 s | 2.839 s |
| Maximum | 2.090 s | 2.839 s |
| Prompt tokens | 9,304 | 15,129 |
| Completion tokens | 3,212 | 7,932 |

Public requests were interpreted by Groq, normalized, guardrailed, optimized, and independently replayed against both returned and organizer directives. Every cost difference was exactly 0 BDT (official tolerance 0.01). No reference schedule was used by the optimizer.

Synthetic results were 8/8 for each of `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, and `no_op`. Type, hour, and numeric comparisons all passed. Cases cover fractions, percentage remaining versus reduction, noon/midnight, decimals, maintenance synonyms, distractors, mixed order, concise notes, and instruction attacks combined with real restrictions. Ground truth is independently maintained in `tests/data/paraphrase_cases.json`; production never loads it.

Latency includes provider calls, parsing/validation, optimizer, and replay; it excludes the 7.5-second pause between benchmark requests. This pacing reduces account throttling and is not added to the production API. These 10- and 16-request samples are too small to guarantee p95 under unseen traffic.

## Development failures and corrections

- An ignored local credential became available after the initial environment check. An early benchmark made 16 calls that failed schema compatibility. Further single-call probes established the rejection cause and the working schema.
- An initial rapid public run passed seven cases and failed three at the provider; the three focused paced reruns passed. A later full paced run passed all ten. Early failures did not preserve status-specific counters, so their exact HTTP codes are not claimed here.
- The first synthetic run reported 27/48, but this conflated provider failures with semantic mistakes and counted every note in a request as wrong on a single mismatch. Accounting now scores notes individually, retains failed-request latency, and stops after persistent provider failure rather than spending the remaining suite's quota.
- The synthetic reserve phrase “through 3 PM” was changed to unambiguous “until 3 PM”; production prompting was not specialized to that test. The complete revised 48-note suite passed. Ambiguous inclusive-end language remains a stated risk, not a solved accuracy claim.
- Final runs used one provider call per request. No text-matching fallback, sample-specific branch, explanation-based retry, or second summary call was introduced.

## Earlier baseline offline and socket checks

| Check | Result |
| --- | --- |
| Original baseline before edits | 211 passed, 10 live tests skipped |
| Final offline pytest | 291 passed, 11 live tests skipped |
| Ruff, compile/import checks, pip dependency check | Passed |
| Official optimizer-only runner | 10/10, exact optimum for every case |
| Local mock socket smoke | Exact health JSON; 24 valid POSTs with eight clients |
| Docker mock socket smoke | Exact health JSON; 24 valid POSTs with eight clients |
| Local real-provider smoke | Exact health JSON; one valid POST, 1.551 s |
| Docker real-provider smoke | Exact health JSON; one valid POST, 1.1483 s |
| Secret scan | No real key or credential-pattern hits in candidate source files, diff, or Git history; `.env` ignored and untracked |
| Docker exclusions | Verified image contains no app `.env`, organizer data, tests, or baked `LLM_API_KEY` environment value |

One upstream Starlette/AnyIO deprecation warning remains. Normal pytest does not require provider access. The real-provider measurements above came from the explicit scripts rather than a duplicate quota-consuming live pytest run.

At that earlier checkpoint, the local image was `gridwise:latest`, ID `sha256:508bd3ae70e7a07eee8dedbfebba9eddac97e20e9ff6ad65118cf3a115d5e6be`. Docker smoke passed the key via runtime environment names, never command arguments containing its value. The Docker context excluded `.env`, tests, organizer data, and Git. That historical local ID was not a pullable registry digest; use the current GHCR digest above.

## Reproduce

```bash
source .venv/bin/activate
pytest -q
ruff check app tests scripts
python -m compileall -q app tests scripts
python -m pip check
python scripts/run_public_cases.py --offline
python scripts/run_public_cases.py --live
python scripts/run_live_benchmark.py
python scripts/smoke_test.py --live
docker build -t gridwise:latest .
python scripts/smoke_test.py --docker-image gridwise:latest --live
```

Restore the organizer JSON to ignored `data/` and configure the local key as described in README. Never paste a key into chat or commit `.env`.

## Remaining risks

Provider quota under concurrent judge requests is the largest operational risk. Longer notes can consume more tokens and truncated output will fail safely after a bounded repair. Strong prompts and guardrails do not prove semantic immunity to all adversarial wording. Overnight/day-boundary phrasing and overlapping solar-reduction precedence remain organizer ambiguities. The remaining submission actions are publishing the video URL, making the GHCR package pullable for evaluators, and changing source visibility only after the official deadline.
