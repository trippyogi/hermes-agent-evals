# Noise / reliability policy

Harness version 0.4.0. This is the reporting contract for stochastic
behavioral cells. It is not a composite score.

## Minimum N

| Use | N | Rule |
|---|---|---|
| Report a binomial rate | **≥ 5** | Below this, publish counts only. Wilson is still computed for debug. |
| First live cell | **10** per arm | Default `HERMES_EVAL_REPS` / `python -m hermes_eval live --reps 10` |
| Unstable / decision-boundary | **20** | If the 95% Wilson width ≥ 0.40, or the point rate sits in [0.40, 0.60] |

Do **not** publish pass@k or pass^k unless N is large enough for a
meaningful estimate. N=10 is not.

Toolperf sanity cells are N=3. They are a frozen external corpus, not a
new claim. Rates are shown with Wilson and flagged `below_policy_min_n`.

## Wilson 95% CI

Implementation: `hermes_eval.stats.wilson_interval` (z = 1.96).

```
center = (p + z²/2n) / (1 + z²/n)
half   = z · sqrt((p(1-p) + z²/4n) / n) / (1 + z²/n)
```

Clipped to [0, 1]. Method label: `wilson`.

## Outcome first

Never treat raw turn count as quality.

- Efficiency (median / IQR turns, tool calls, tokens, duration) is
  computed **only on successful runs**.
- Failure cost is a separate table (turns before fail/abandon, pseudo
  attempts, tokens, duration).
- Mixing success and abandon into one mean is a bug.

A 6-turn recovery that succeeds can beat a 2-turn abandon.
`err_case_search` is the opposite: same 100% outcome, 3.3 → 9.3 turns
is inefficiency.

## Control validity

A fault-arm comparison is **invalid** unless CONTROL shows the model
can actually use tools:

- N ≥ 5
- CONTROL task-success rate ≥ 0.50 (externally verified)

If invalid, publish CONTROL numbers and withhold FAULT interpretation.
Do not invent a story from fault-arm text dumps.

Fault-arm **task success is expected ≈ 0**. Known-good makes an empty
toolset loud; it does not restore tools.

## Infra vs provider / template failures

| Class | Example | Retry? |
|---|---|---|
| Provider/template failure | Completed oneshot that emits raw `<function=...>`, JSON-in-text, or a hallucinated "I wrote the file" | **No.** Own failure class. |
| Infra startup | `ModuleNotFoundError`, missing interpreter, process never started, no usage file and no completed model response | **Yes, once**, and only if it happens **before** the eval run begins. **Never enter the denominator** for control/fault behavioral rates or Wilson intervals. |
| Completed | Normal model finish, success or fail | **No** |

A completed bad model response is a result. Silently retrying it until
it passes would erase the failure class this cell exists to measure.

## Isolation and secrets

- Isolated temp `HERMES_HOME` only. Never read `~/.hermes`.
- Credentials: process env `HERMES_EVAL_*` only. Fingerprinted, never stored raw.
- Isolation is the SUT checkout path, not a second venv.
- Prefer `HERMES_EVAL_PYTHON` pointing at the Hermes checkout interpreter.
