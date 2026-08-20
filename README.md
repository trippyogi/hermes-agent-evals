# hermes-agent-evals

Local research harness for **Hermes agent-behavior regressions**.

It answers:

- Did Hermes version X measurably regress this agent behavior?
- Did fix Y improve task success, recovery, efficiency, or state correctness?

Historical validation is the gate: a fixture is useful only if it can
separate a known-bad Hermes SHA from a known-good/fixed SHA.

v0.4 adds **live behavioral statistics**: Wilson rates, failure-mode
splits, and efficiency *given success*. The live `zero-toolset-live`
cell is BLOCKED without `HERMES_EVAL_*` and does not invent rates.
v0.3 made **TraceV1** the scoreable artifact. v0.3.1 ingested the
canonical August 6 `hermes-toolperf-evals` ATOF archive (108 runs) as
an external sanity set. The deterministic canary stays on maintenance.

v0.2 proved **portability** (clean clone + GitHub fetch).

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

`hermes-toolperf-evals` is the canonical production-derived tool-efficiency
experiment: nine induced-failure tasks, real model runs, and a checked-in
ATOF archive. This repo does **not** duplicate those tasks. v0.3.1
imports the August 6 rerun into TraceV1 (`python -m hermes_eval
ingest-toolperf`) and re-scores it.

This repo is the general regression / behavioral observability layer:
TraceV1, historical canaries, state invariants, re-scoring, and future
behavioral corpora. Read-only input; no writes to the Nous toolperf repo.

Do not optimize raw turn count. Separate outcome, efficiency given
success, recovery cost, and failure quality. No composite score yet.

## Upstream policy

- **No GitHub writes to NousResearch/hermes-agent.** Hermes is the system
  under test. This harness is research-only.
- A fixture becomes a possible Hermes upstream contribution only when it
  catches a real regression, separates known-good from known-bad, the
  invariant is long-term, maintainers would run it permanently, and CI
  cost is reasonable.
- Until then, keep it external.

## Layout

```
evals/fixtures/      fixture YAML (id, classification, known_bad/good SHAs)
evals/provenance/    immutable SHA manifest, frozen expected splits, canary index
evals/runners/       isolated SUT drivers (emit observations)
evals/scorers/       component metrics + ancestry-aware canary
evals/schemas/       fixture, result, and TraceV1 contracts
evals/suites/        core-failures
hermes_eval/         CLI, TraceV1 adapters/scorers
hermes_eval/trace/   TraceV1 model, adapters, re-score
reports/evals/       architecture, corpus, taxonomy, results
.github/workflows/   historical 3/3 on PR; scheduled current canary
```

## How to run (portable)

Use an isolated temp `HERMES_HOME`. The harness never reads `~/.hermes`.

From a clone of this repo (any machine with git + a Python that can import
Hermes deps, or `HERMES_EVAL_PYTHON` pointing at such an interpreter):

```bat
git clone https://github.com/trippyogi/hermes-agent-evals.git
cd hermes-agent-evals
set PYTHONPATH=%CD%
rem Optional: reuse an existing Hermes venv. Isolation is the SUT checkout,
rem not a second venv. PYTHONPATH must point at the fetched worktree.
rem set HERMES_EVAL_PYTHON=C:\path\to\hermes\.venv\Scripts\python.exe

python -m hermes_eval fetch-sut
python -m hermes_eval freeze
python -m hermes_eval compare --historical --suite core-failures
python -m hermes_eval canary
python -m hermes_eval trace rescore --trace results\<run>\trace.json
python -m hermes_eval trace atof evals\fixtures\_trace_samples\atof-sample.jsonl
python -m hermes_eval ingest-toolperf
python -m hermes_eval adjudicate-atof
python -m hermes_eval analyze
python -m hermes_eval run --fixture delegate-fallback-runtime --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1
python -m hermes_eval live --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1 --reps 10
python -m hermes_eval probe-prefix --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1
python -m hermes_eval scan-waste evals/fixtures/_waste_samples --out results/wasted-turn-scan.json --label-sheet
```

Unix-style equivalent:

```sh
git clone https://github.com/trippyogi/hermes-agent-evals.git
cd hermes-agent-evals
export PYTHONPATH="$PWD"
python -m hermes_eval fetch-sut
python -m hermes_eval compare --historical --suite core-failures
```

`fetch-sut` pulls historical SHAs from GitHub into `.cache/hermes-sut` and
materializes detached checkouts under `.worktrees/<sha12>`. Result JSON
records that clone-local `hermes_root`. Operator filesystem paths are not
required. Replay provenance stays in `evals/provenance/manifest.json`.

`--historical` scores **from TraceV1**, not runner extras. Each run writes
`trace.json` beside `result.json`. `python -m hermes_eval trace rescore`
re-scores a stored trace. `--runner-score` is an escape hatch.

`--historical` uses each fixture YAML’s own known-bad / known-good pair
(required for the gate: the three fixes live on different SHAs).

`canary` fetches `refs/heads/main`, stores the **full SHA** (never the
branch label), runs the three fixtures, and interprets with ancestry-aware
statuses: `PASS` | `REGRESSION` | `FIX_NOT_ON_THIS_SHA` |
`PASS_WITHOUT_FIX_SHA` | `INDETERMINATE`. `REGRESSION` is recorded only
when `known_good` is an ancestor of that SHA **and** the fixture failed.

CLI aliases exist only as input sugar and expand through
`evals/provenance/manifest.json`. **Results always store full SHAs.**
Do not record `origin/main` or branch names in artifacts.

Optional env:

- `HERMES_EVAL_PYTHON` — interpreter that can import Hermes (else `sys.executable`)
- `HERMES_EVAL_SUT_REMOTE` — override fetch remote
- `HERMES_EVAL_SUT_CACHE` — override cache dir
- `HERMES_EVAL_ALLOW_FETCH=0` — disable network fetch
- `HERMES_EVAL_SUT_SOURCES` — extra local clones (never required)
- `HERMES_EVAL_ATOF_DIR` — real ATOF traces for waste labeling
- `HERMES_EVAL_TOOLPERF_RERUN` — path to `results/2026-08-06_rerun` (default: sibling `../hermes-toolperf-evals/results/2026-08-06_rerun`)
- `HERMES_EVAL_TOOLPERF_CACHE` — extracted ATOF cache (default: `.cache/toolperf-2026-08-06`)

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

None of the historical three is `production_replay`. Honest labels are in
each fixture YAML.

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
- optional `HERMES_EVAL_BASE_URL`, `HERMES_EVAL_REPS` (default 10),
  `HERMES_EVAL_TEMPERATURE` (default 0), `HERMES_EVAL_REASONING`

If those are absent the live runner records `status=BLOCKED` and does
not invent rates. Known-good makes zero tools **loud**; it does **not**
restore tools. Report CONTROL and FAULT rates separately, with Wilson
intervals. Efficiency is computed only on successful CONTROL runs.
Fault-arm task success is expected ~0 and is not evidence the salvage
commit fixed the task.

`python -m hermes_eval analyze` writes
`reports/evals/v0.4-live-behavioral-statistics.md` from a live
`result.json` plus the cached toolperf ingest. Policy:
`reports/evals/noise-reliability-policy.md`.

Hermes Behavioral Observatory remains **NOT READY** until a
production-derived behavioral metric is adjudicated (v0.4.1).
