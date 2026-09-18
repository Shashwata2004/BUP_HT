# GridWise video script

Target length: about 2 minutes 40 seconds.

## Spoken script

**0:00–0:25 — Problem**

GridWise schedules a campus's electricity use over 24 hours. Each request supplies hourly demand, solar forecast, tariff data, battery limits, and up to three natural-language operator notes. The service must understand those notes, obey every energy constraint, minimize grid cost, and return an exact machine-checkable API response.

**0:25–1:05 — Architecture**

The request first goes to Groq's `openai/gpt-oss-120b` model. The model has one narrow job: convert each untrusted operator note into one of the six official structured directive types. Deterministic guardrails then reject wrong note indexes, unsupported fields, invalid hours, inconsistent `applies` values, or out-of-range numbers. No model output reaches scheduling until it passes these checks.

**1:05–1:40 — Optimization and validation**

SciPy HiGHS solves the schedule as a linear program. It minimizes tariff-weighted grid imports while enforcing hourly energy balance, effective solar, battery capacity and reserve, charge and discharge rates, grid caps, restricted windows, and end-of-day battery neutrality. The language model never creates the schedule. After solving, an independent replay validator reconstructs all 24 hours from the original request and directives, checks every constraint again, and recalculates the totals.

**1:40–2:15 — Evidence**

The offline suite has 1,592 passing tests. All ten official optimizer cases match the organizer's optimum exactly, and all ten pass through the live Groq path. A separate 150-note hidden-style suite and a final 54-note semantic red team both pass completely. We also replayed 1,000 deterministic randomized scenarios, checked independent optimality oracles, fuzzed invalid API requests, and tested 100 concurrent calls. Secrets remain outside source control and the container image.

**2:15–2:40 — Submission paths**

The public Render endpoint exposes `GET /health` and `POST /optimize-energy` over HTTPS without judge authentication. The same application is published as a digest-pinned GHCR image for fallback reproduction. The README provides local setup, exact environment-variable names, test commands, API examples, and Docker commands. This gives judges the same LLM-to-guardrail-to-optimizer-to-validator pipeline through either deployment path.

## Screen-recording shot order

1. Show the README architecture flow and required endpoints.
2. Show `app/interpreter.py` briefly, focusing on untrusted notes and structured output.
3. Show `app/optimizer.py` and `app/validator.py` side by side.
4. Run or show the final `pytest` result and the 10/10 public-case result.
5. Call the public `/health`, then show one successful `/optimize-energy` response.
6. Show the Render service URL and the GHCR image reference/digest from `docs/submission-info.md`.
