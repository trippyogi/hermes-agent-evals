# Compression / prefix-churn observability

Investigation only. Hermes core was not modified.

## Question

Does the reusable conversation prefix stay stable when nothing about the
system prompt, toolset, or compressed prefix should have changed?

## What exists today

| Signal | Where | Observable this pass? |
|---|---|---|
| System prompt hash | Not exported | no |
| Cached-prefix hash | Not exported | no |
| Messages per turn | Session DB / ATOF | not collected |
| Compression event count | `ContextCompressor` internals | not without a live compress() |
| Context tokens before/after | usage / ATOF | not_observable (no provider) |
| Provider `cache_read` / `cache_write` | `hermes -z --usage-file` | seam exists; needs a real model |
| NeMo Relay ATOF | toolperf-evals | not enabled |
| Tool-result content md5 | `context_compressor.py` dedup | **not** a request-prefix identity |

`hermes-compression-eval` grades **summary quality** after
`ContextCompressor.compress()`. It is not a prefix-cache meter. Prior
#89515 notes: the issue’s prefix-identity claim was false on main; a later
keyed run should monkeypatch `call_llm` **in the harness**, not fork the
compressor.

## Tiny probe (harness-owned)

Two synthetic turns, no toolset change, no compression:

- prefix hash turn1 = `c0ad098ee9cebc90`
- identical replay = same hash (`stable_when_unchanged=true`)
- full hash after suffix growth changes (`5d5017ab1b86bc9b`)

This only proves the **harness** can hash a prefix. It does **not** prove
Hermes reused a provider cache.

## Instrumentation seam (this pass, still external)

The harness wraps `AIAgent._build_api_kwargs` and
`AIAgent._interruptible_api_call` (plus `ContextCompressor.compress` when
present). For each LLM call it records **hashes only**:

- `system_prompt_hash`
- `tool_schema_hash`
- `stable_message_prefix_hash` (first k messages)
- `message_count`
- `input_tokens` / `cache_read_tokens` / `cache_write_tokens` when the
  mock/provider usage object exposes them
- compression event flag

No prompt text is stored. Hermes core is not modified.

Command:

```
python -m hermes_eval probe-prefix --ref 13ce0c5c675e843af70d19c9e5144249cd51c8d1
```

If `run_conversation` cannot complete under the wrap, the probe still
hashes `_build_api_kwargs` payloads. That is the real outgoing request
dict Hermes would send, even when the network hop is mocked.

Provider `cache_read` on a live model remains a separate measurement
and stays `not_observable` without `HERMES_EVAL_*` credentials.
