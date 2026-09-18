# Baseline verification record

Run locally on 2026-09-18 with Python 3.12.3 and Docker Engine 29.2.1. This records observed results, not a hidden-judge score or live-provider performance claim.

| Check | Observed result |
| --- | --- |
| `pytest -q` | 211 passed; 10 live tests explicitly skipped. One upstream Starlette/AnyIO deprecation warning. |
| `ruff check app tests scripts` | Passed. |
| `python -m compileall -q app tests scripts` | Passed. |
| `pip check` | No broken requirements. |
| `python scripts/run_public_cases.py --offline` | 10/10 valid, exactly equal to each stated reference optimum. |
| Independent optimizer oracle | 50 seeded small scenarios compared with exhaustive integer battery-state DP; feasible costs and infeasibility matched. |
| Local socket smoke | Health 200 with exact JSON; 24 valid POST responses with eight concurrent clients and a mock provider. |
| Docker build | `docker build -t gridwise:prompt-01 .` succeeded. |
| Docker socket smoke | `python scripts/smoke_test.py --docker-image gridwise:prompt-01` succeeded: health and 24 replay-valid POSTs. |
| Secret/config exclusions | `.env`, `.env.production`, `.venv`, `.artifacts`, build logs ignored; Docker uses explicit context allowlist. |
| Official source integrity | Copies in `data/` verified byte-for-byte against supplied source files using SHA-256. |

All three organizer source files were read before coding. No prompt injection was detected. The PDFs and JSON were copied without edits; the production application never reads them.

## Public cost results

| Case | Our cost (BDT) | Organizer cost (BDT) | Difference |
| --- | ---: | ---: | ---: |
| SAMPLE-01 | 38365 | 38365 | 0 |
| SAMPLE-02 | 42885 | 42885 | 0 |
| SAMPLE-03 | 35480 | 35480 | 0 |
| SAMPLE-04 | 40495 | 40495 | 0 |
| SAMPLE-05 | 33950 | 33950 | 0 |
| SAMPLE-06 | 34090 | 34090 | 0 |
| SAMPLE-07 | 38550 | 38550 | 0 |
| SAMPLE-08 | 37665 | 37665 | 0 |
| SAMPLE-09 | 34873 | 34873 | 0 |
| SAMPLE-10 | 41620 | 41620 | 0 |

Local guardrail/optimizer/replay timing on the first recorded public run was 0.002–0.012 seconds per case. A local mock-provider concurrency smoke run had a maximum request time of 0.0881 seconds; a Docker smoke run had a maximum of 0.1957 seconds. These are integration/mathematics measurements with a mock model, not real LLM latency. Subsequent timings vary with process startup and scheduling.

## Tested Docker artifact

Local tag: `gridwise:prompt-01`.

Image ID: `sha256:3fe47d350b5387497003bafb0d6cf7f3c06898ae421cad364eadbea75fb9c756`.

Reported local image size: 116,700,640 bytes. Runs as user `gridwise`, exposes port 8000, and binds `0.0.0.0`. The image ID is a local artifact identifier, **not** a pullable registry digest. No registry push was performed.

## Explicitly unverified / remaining submission work

- No `LLM_API_KEY` or `LLM_MODEL` is configured. Real provider compatibility, note accuracy/paraphrases, quota, and end-to-end p95 have not been measured. Run the documented live tests after configuring these.
- No public deployment, external-network endpoint check, or pullable registry image is provided in this phase.
- The required ≤3-minute submission video is not created.
- Overlapping solar-reduction precedence needs organizer clarification; the implemented literal assignment assumption is documented in acceptance criteria.
