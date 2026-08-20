# hermes-agent-evals

Local research harness for **Hermes agent-behavior regressions**.

It answers:

- Did Hermes version X measurably regress this agent behavior?
- Did fix Y improve task success, recovery, efficiency, or state correctness?

Historical validation is the gate: a fixture is useful only if it can
separate a known-bad Hermes SHA from a known-good/fixed SHA.

## Why this exists

NousResearch/hermes-agent has unit tests and an in-tree `scripts/toolperf_abeval/`
copy. `NousResearch/hermes-toolperf-evals` is Teknium’s A/B battery for
core-tool schema waste (fewer wasted tool turns after induced errors).

This repo is a **different question**: given a runtime/session state and a
task (or a state transition), does this Hermes revision recover, execute the
intended capability, and finish without corrupting state?

It lives **outside** hermes-agent on purpose.

## What this is NOT

- Not a leaderboard
- Not a generic LLM benchmark
- Not a replacement for Hermes unit tests
- Not an excuse to upstream every fixture
- Not BATON / campaign orchestration
- Not a second `abeval/` orchestrator and not a product plugin

## Relationship to hermes-toolperf-evals

`C:\dev\hermes-toolperf-evals` stays the home of the 9-trap A/B toolperf
battery. This repo is the dedicated research tree for the
agent-behavior / state-recovery / instrumentation split, with a compare
runner and a historical-validation gate.

## Upstream policy

- **No GitHub writes during this task.** No PRs, no issue comments, no
  push to NousResearch/hermes-toolperf-evals (READ-only clone).
- A fixture becomes a possible Hermes upstream contribution only when it
  catches a real regression, separates known-good from known-bad, the
  invariant is long-term, maintainers would run it permanently, and CI
  cost is reasonable.
- Until then, keep it external.

## Layout

```
evals/fixtures/      fixture YAML (id, classification, known_bad/good SHAs)
evals/provenance/    immutable SHA manifest + frozen expected splits
evals/runners/       isolated SUT drivers
evals/scorers/       component metrics + regression flags
evals/schemas/       fixture + result contracts
evals/suites/        core-failures
hermes_eval/         CLI
reports/evals/       architecture, corpus, taxonomy, results
```

## How to run

Use an isolated temp `HERMES_HOME`. The harness never reads `~/.hermes`.

```bat
cd C:\dev\hermes-agent-evals
set PYTHONPATH=C:\dev\hermes-agent-evals
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval manifest
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval compare --historical --suite core-failures
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval run --fixture delegate-fallback-runtime --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval run --fixture delegate-fallback-runtime --ref c6a2fb48af74e3c795015aeb6e615733a9b5bac5
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval live --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1 --reps 5
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval probe-prefix --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1
c:\dev\hermes-agent\.venv\Scripts\python.exe -m hermes_eval scan-waste evals/fixtures/_waste_samples --out results/wasted-turn-scan.json --label-sheet
```

`--historical` uses each fixture YAML’s own known-bad / known-good pair
(required for the gate: the three fixes live on different SHAs).

CLI aliases exist only as input sugar and expand through
`evals/provenance/manifest.json`. **Results always store full SHAs.**
Do not record `origin/main` or branch names in artifacts.

## Pinned Hermes SHAs

See `evals/provenance/manifest.json`. Summary:

| Role | Full SHA |
|---|---|
| known-bad (pinned 2026-08-19 main) | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` |
| empty-toolset salvage | `ed5b9152ce975ada68f0b53a21c4806f29ed0852` |
| #90209 delegate fix (eval known_good) | `c6a2fb48af74e3c795015aeb6e615733a9b5bac5` |
| #90209 prior PR-open SHA (not eval known_good) | `465f0d4872cf616ff0a095b7b48b506fd377876a` |
| #90021 pin-scope fix (eval known_good) | `623b93200779d31d416eb2c5f9116106de6f5adb` |
| #90021 prior report SHA (not eval known_good) | `3582a128c767a206713cdd4ae1cc6b770144539b` |

## Fixture classifications

- `production_replay` — replays a real production trace/session
- `fault_injected_invariant` — injects a documented bad state because the
  historical SHA does not naturally produce the discriminator
- `state_transition` — protocol/FSM correctness, not an LLM task
- `agent_behavior` — model + environment; control vs fault
- `instrumentation` — measurement probe, not a pass/fail SUT by itself

Honest labels for the current corpus are in each fixture YAML.

## Result format

JSON + compact Markdown. Every run records:

- Hermes git SHA (full)
- harness SHA (full; `null` only if the eval repo is not a git checkout)
- harness_dirty
- fixture version + fixture schema version
- classification
- model / provider
- OS/runtime
- timestamp

Secrets are fingerprinted (`anthropic-key:<12 hex>`), never stored raw.
`null` plus `not_observable` means the metric is defined but was not
available on that run. There is no single collapsed score.

## Tiers

1. Deterministic foundation (runtime identity, pin FSM, protocol)
2. Controlled model + deterministic env (fake model for zero-toolset;
   live weak-model arm is separate and may be BLOCKED)
3. Open-ended — not started

## Live eval credentials

Copy `.env.example` values into the **process environment** only:

- `HERMES_EVAL_PROVIDER`
- `HERMES_EVAL_MODEL`
- `HERMES_EVAL_API_KEY`
- optional `HERMES_EVAL_BASE_URL`, `HERMES_EVAL_REPS`

If those are absent the live runner records `status=BLOCKED` and does
not invent rates.
