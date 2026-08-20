# Roadmap

Two products:

1. **Hermes Regression Canary** — cheap, deterministic, commit-level.
   Ready as of v0.2; v0.3 makes it re-scoreable from TraceV1 and runs it
   in GitHub Actions. Maintenance only. Do not expand it.
2. **Hermes Behavioral Observatory** — slower, repeated model runs.
   **NOT READY.** v0.4 shipped the statistics pipeline, noise policy,
   and toolperf sanity check. The first live cell is BLOCKED without
   `HERMES_EVAL_*` unless a later run records `status=RUN`. READY also
   requires at least one adjudicated production-derived behavioral
   metric (v0.4.1).

| Milestone | Goal | Main output | Gate |
|---|---|---|---|
| v0.3 Trace spine | Neutral representation | TraceV1 + adapters + re-scoring | Existing 3 fixtures reproduce from trace |
| v0.3.1 Toolperf ingestion | External validation | 108-run ATOF archive → TraceV1 | Metric identity vs abeval; no new fixtures |
| v0.4 Behavioral statistics | Stochastic behavior | Analysis utilities + live cell + policy | Wilson / efficiency-given-success / toolperf sanity. Live may be BLOCKED. |
| v0.4.1 Waste adjudication | Label real ATOF waste | 13 toolperf episodes, human verdicts | Adjudicated production-derived metric |
| v0.5 Stateful task contract | Grade outcomes without one trajectory | State/frame-condition scorer | Correct alternative trajectories pass |
| v0.6 Production corpus | Mine real Hermes behavior | Adjudicated ATOF → promotable fixtures | Human-labeled production evidence |
| Later harness comparison | Separate model from harness | Hermes/Pi/OpenClaw adapters | Same task, same model, different harness |

Do not expand the reconstructed waste corpus this pass. Do not start a
Hermes-vs-Pi-vs-OpenClaw leaderboard. Stubs exist in
`hermes_eval/harness_adapters.py`.

v0.4 measurements (when live RUN exists and CONTROL is valid):

- `control_task_success_rate` + Wilson 95% CI
- `fault_task_success_rate` + CI (expect ≈ 0)
- `fault_textual_pseudo_tool_call` split: JSON-like / XML `<function=...>` / other
- `fault_hallucinated_completion_rate`
- `fault_explicit_capability_failure_rate`
- `fault_diagnostic_rate`
- efficiency **given CONTROL success**: median/IQR turns, tool calls, tokens, duration
- failure cost on failed runs
- N, min/max

Do not add pass@k until N supports it. No composite score.

Fault-arm **task success stays ~0**. Known-good is loud, not tool restoration.

## Next (information gain)

1. **v0.4.1** — human adjudication of the 13 real ATOF waste episodes.
2. **v0.5** — state/frame-condition contract.
3. **v0.6** — production mining.
