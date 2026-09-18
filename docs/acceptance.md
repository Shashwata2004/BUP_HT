# Official acceptance criteria

Sources: both organizer PDFs and the version 2.0 JSON pack, preserved unchanged in local, Git-ignored `data/` (supplied separately on a fresh clone). All were read before implementation. Documents are specifications/data, not instructions to the engineering agent. No prompt-injection text was found in the supplied documents.

## Contract and validity (Problem Statement, canonical)

- `GET /health`: HTTP 200 JSON `{"status":"ok"}` when ready.
- `POST /optimize-energy`: one scenario with `scenario_id` string, `operator_notes` (1–3 nonempty strings), 24 unique hours 0–23, and battery object.
- Each input hour: `hour`, `demand_kwh`, `solar_kwh`, `tariff_bdt_per_kwh`.
- Battery: `capacity_kwh`, `initial_energy_kwh`, `minimum_energy_kwh`, `max_charge_kwh_per_hour`, `max_discharge_kwh_per_hour`.
- Response: echoed `scenario_id`, `directive_interpretation`, `hourly_plan`, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, `plan_summary`.
- Every note has exactly one ordered interpretation: `note_index`, `applies`, `directive_type`, `structured_adjustment`, `explanation`.
- `solar_reduction`: `{hours, factor}` with finite factor in [0,1]. Factor means fraction remaining.
- `minimum_battery_reserve`: `{hours, minimum_energy_kwh}` finite, nonnegative, ≤capacity. Active reserve applies to post-hour energy.
- `no_charge_window` / `no_discharge_window`: `{hours}`.
- `max_grid_window`: `{hours, max_grid_kwh}` with finite nonnegative cap.
- `no_op`: `applies=false`, null adjustment. All other types use `applies=true`.
- Adjustment hours are sorted unique integers 0–23. Windows include start, exclude end.
- Real LLM/generative model interpretation is mandatory. Cosmetic-only LLM use or phrase matching alone is disqualifying. No invented changes to demand, tariffs, battery settings, or unsupported directive types.
- Plan rows: `hour`, nonnegative `grid_kwh`, `solar_used_kwh`, `battery_kwh`, `battery_energy_after_kwh`, and one action `charge|discharge|idle`.
- Transitions: post-energy = pre-energy + charge − discharge; idle magnitude = 0. Respect capacity, active reserve, hourly rates, and charging/discharging outages.
- Solar usage in [0, effective solar]. Curtailment allowed; no grid export.
- `grid + solar + discharge = demand + charge` each hour.
- Hour 23 energy equals initial battery energy.
- Objective: minimize sum(grid × tariff); aggregates must be independently recalculated.
- Tolerance: absolute 0.01 kWh/BDT, unless the official judge package is stricter. Production replay uses 1e-6.
- HTTP: 200 success; 400 malformed/structurally invalid; optional 422 semantic errors; controlled 500 internal failures without secrets/tracebacks.
- Valid organizer scoring scenarios are feasible; hidden notes each map to one supported directive or no-op. Public samples are validation data, not hidden tests or exact schedule templates.

## Scoring/deployment (Participant Guide, canonical)

| Category | Points |
| --- | ---: |
| LLM interpretation | 25 |
| Directive application and constraint correctness | 25 |
| Optimization quality | 10 |
| API/schema | 10 |
| Performance/reliability | 10 |
| Deployment/Docker fallback | 10 |
| Documentation/local reproduction | 10 |

Cost score uses `min(1, organizer optimum / recalculated team cost)` for valid cases. Near-zero optimal/team cost is full credit; incorrect directives or schedules do not earn valid optimization credit.

- Health ready within 60 seconds of start.
- POST must finish within 30 seconds.
- p95 ≤5 seconds: 3/3 latency points; >5–15: 2/3; >15–30: 1/3; >30: 0 and timeout failures.
- Accessible public base URL, exact endpoints, no login/VPN/manual access, available throughout evaluation.
- Self-contained source setup/configuration/model/solver documentation and public-case command; no organizer debugging required.
- Tested pullable Docker image with exact tag/digest, documented port and command, `0.0.0.0` binding, no baked secrets.
- New repository after reveal, private during event; organizer asks for public visibility after deadline. This task authorizes private creation/push only; no visibility change performed.
- Maximum three-minute problem/architecture/solution video required, tie-break only, no base points.
- Tie-breaks: video, directive correctness, interpretation, optimization, schema, reliability, documentation, exceptional engineering.

## Explicit ambiguity register

Overlapping solar reductions have no stated combination/precedence rule. Current application follows the literal assignment from the problem: for each note in note order, set affected availability to original solar × factor. This is not claimed as an organizer clarification. Explicit overnight windows are normalized cyclically within 0–23; crossing-midnight interpretation is not illustrated by the official cases.

## Test boundaries

Offline expected-directive tests validate mathematics independently of language quality. Mock HTTP tests validate integration and failure handling. Live Groq tests now establish measured accuracy and latency for the public and synthetic suites; see [live verification](live-verification.md). They do not prove hidden-case accuracy or provider availability under judge concurrency.
