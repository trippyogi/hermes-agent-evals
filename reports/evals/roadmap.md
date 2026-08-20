# Roadmap

Two products:

1. **Hermes Regression Canary** — cheap, deterministic, commit-level.
   Ready as of v0.2; v0.3 makes it re-scoreable from TraceV1 and runs it
   in GitHub Actions.
2. **Hermes Behavioral Observatory** — slower, repeated model runs.
   Not ready. Live matrix still BLOCKED without `HERMES_EVAL_*`.

| Milestone | Goal | Main output | Gate |
|---|---|---|---|
| v0.3 Trace spine | Neutral representation | TraceV1 + adapters + re-scoring | Existing 3 fixtures reproduce from trace |
| v0.4 Behavioral statistics | Stochastic behavior | Repeated live cells, reliability/noise | Real distributions, not anecdotes |
| v0.5 Stateful task contract | Grade outcomes without one trajectory | State/frame-condition scorer | Correct alternative trajectories pass |
| v0.6 Production corpus | Mine real Hermes behavior | Adjudicated ATOF → promotable fixtures | Human-labeled production evidence |
| Later harness comparison | Separate model from harness | Hermes/Pi/OpenClaw adapters | Same task, same model, different harness |

Do not expand the reconstructed waste corpus. Do not start a
Hermes-vs-Pi-vs-OpenClaw leaderboard. Stubs exist in
`hermes_eval/harness_adapters.py`.

v0.4 measurements (when live RUN exists):

- `control_task_success_rate`
- `fault_textual_pseudo_tool_call_rate`
- `fault_malformed_tool_like_text_rate`
- `fault_diagnostic_rate`
- turns, tool calls, tokens, latency
- N, median, IQR, min/max, Wilson CI
- later: pass@k and pass^k

Fault-arm **task success stays ~0**. Known-good is loud, not tool restoration.
