# Architecture survey

Research notes. No Hermes source edits. Isolated `HERMES_HOME` only.

## Cleanest way to launch Hermes reproducibly?

1. **Detached git worktree** of the SUT SHA (or an existing matching worktree).
2. **Isolated temp `HERMES_HOME`** with a synthetic `config.yaml` / empty `.env`.
3. **One-shot** for live chat: `hermes -z` / `hermes_cli.oneshot.run_oneshot`
   (`HERMES_YOLO_MODE=1`, `--usage-file` for tokens). Quiet, no TUI.
4. **PYTHONPATH = that worktree**, not an editable install of whatever
   checkout happens to be on `PATH`.

This harness uses (1)+(2) always. Live `-z` against a real model is not
required for the first corpus. `abeval/` in hermes-toolperf-evals remains
the POSIX path for `hermes chat` + NeMo Relay ATOF.

Do not launch against the user's default `~/.hermes`.

## How do we pin a Hermes commit/ref?

`--ref` is a SHA, alias, or checkout path. `hermes_eval.gitutil.resolve_hermes_root`
looks up a local object and either reuses a known worktree or
`git worktree add --detach` under `.worktrees/<sha12>`. No fetch, no GitHub
write. The result JSON stores the full SHA.

## How do we isolate HERMES_HOME?

`tempfile.mkdtemp(prefix="hermes-eval-home-")`. Set `HERMES_HOME` in the
child env. Strip inherited `*_API_KEY` / `*_TOKEN`. `hermes_constants.get_hermes_home()`
honors the env var before the platform default. Never set `HERMES_HOME` to
the user's real profile.

## How do we capture transcript / events?

| Source | What | Used here |
|---|---|---|
| Runner-owned `events[]` | Structured llm/tool/patch records | Yes |
| `hermes -z --usage-file` | tokens, api_calls, model | Seam only |
| Session `state.db` | SQLite under HERMES_HOME | Not opened this pass |
| NeMo Relay ATOF | Ground-truth llm/tool turns | Documented; not enabled |
| Desktop pin-sync | PATCH log | Simulated at store boundary |

## How do we measure token usage?

OnesHot writes `input_tokens` / `output_tokens` / `cache_read_tokens` /
`cache_write_tokens` when the provider reports them. ATOF traces do the
same. This pass: **not_observable** on hermetic fixtures (no live provider).

## How do we count actual tool executions?

Count structured tool events the runner dispatched (or ATOF `tool` starts).
A JSON blob in assistant text is **not** a tool execution.

## Valid vs invalid / wasted tool calls?

- **Invalid:** schema-less / unregistered name, or dispatch that never ran.
- **Wasted (conservative):** identical retry after a deterministic failure
  with no recorded state change; tool against a dead runtime; textual
  pseudo-call when schemas were zero. Parser emits **candidates** for
  labeling — not ground truth.

## Can we observe cache / prefix reuse?

Not on the wire without a provider that returns `cache_read` / `cache_write`,
or NeMo Relay. Hermes `ContextCompressor` hashes tool-result text for
dedup; it does **not** export a request-prefix identity. Instrumentation
seam: monkeypatch `call_llm` *inside this harness* later. Do not patch
Hermes core.

## How can faults / state be injected without modifying Hermes?

| Fault | Injection |
|---|---|
| Zero toolset | Isolated `config.yaml` `platform_toolsets.cli: []` |
| Fallback then delegate | Construct parent + `_try_activate_fallback` + `_build_child_agent` |
| Pin rescope | Drive pin/unpin/setConnection against the SUT pin-scope policy |
| Fake model | Deterministic tool-call vs text dump in the runner |

No product-tree edits. No user config.

## Fake provider vs real model?

| Scenario | Need |
|---|---|
| Pin rescope, runtime identity | **No model** (Tier 1) |
| Zero-toolset loud-failure + control proof | **Fake model** (Tier 2) is enough |
| Toolperf-style recovery quality | Real weak model + ATOF, later |
| Compression quality | `hermes-compression-eval` + keys, later |

## Existing tooling we did not reimplement

- `hermes-toolperf-evals/abeval` — 9 traps, PYTHONPATH arms, ATOF
- `hermes-compression-eval` — probe/judge quality of `compress()`
- In-tree `scripts/toolperf_abeval/` — same A/B harness, less data
