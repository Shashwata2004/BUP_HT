# Live Groq verification

Verified on 2026-09-18. These results measure this local environment and account, not hidden judge performance or burst capacity. The optimizer, replay validator, public API schemas, endpoints, and solver dependencies were preserved.

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

## Final complete live runs

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

## Offline and socket checks

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

Local image: `gridwise:latest`, ID `sha256:508bd3ae70e7a07eee8dedbfebba9eddac97e20e9ff6ad65118cf3a115d5e6be`. Docker smoke passes the key via runtime environment names, never command arguments containing its value. The Docker context excludes `.env`, tests, organizer data, and Git. The image has not been pushed to a registry; this local ID is not a pullable submission reference.

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

Provider quota under concurrent judge requests is the largest operational risk. Longer notes can consume more tokens and truncated output will fail safely after a bounded repair. Strong prompts and guardrails do not prove semantic immunity to all adversarial wording. Overnight/day-boundary phrasing and overlapping solar-reduction precedence remain organizer ambiguities. Public deployment, registry publication, external reachability verification, and the required video remain later submission work.
