# First results — historical validation

**Date:** 2026-08-19  
**Harness:** `C:\dev\hermes-agent-evals` (uncommitted; `harness_sha=null`)  
**Command:**

```
python -m hermes_eval compare --historical --suite core-failures --out results/compare-core-failures-historical
```

**Gate: PASSED — 3 / 3 fixtures distinguished known-bad from known-good.**

Same-SHA-pair compare (`--baseline 13ce0c5c --candidate <one fix>`) cannot
fix all three bugs at once. `--historical` uses each fixture YAML’s
`known_bad` / `known_good`.

Machine-readable: `results/compare-core-failures-historical/compare.json`  
Human: `results/compare-core-failures-historical/compare.md`

## zero-toolset

| | Bad `13ce0c5c67` | Good `ed5b9152ce` |
|---|---|---|
| success | FAIL | PASS |
| control proof | yes (`write_file`, nonce written) | yes |
| fault schemas | 0 | 0 |
| fault tool executions | 0 | 0 |
| textual pseudo-call | true | true |
| `warning_emitted` | **false** | **true** |
| recovered | false | true |
| turns | 1 | 1 |
| tool_calls (control+fault) | 1 | 1 |
| tokens | not_observable | not_observable |

Discriminator is **loud failure**, not turn count. Fail-closed tools stay zero
on both arms. Fake model: structured `write_file` when schemas exist, JSON
text dump when they do not.

## delegate-fallback-runtime (#90009)

| | Bad `13ce0c5c67` | Good `c6a2fb48af` |
|---|---|---|
| success | FAIL | PASS |
| fallback_activated | true | true |
| runtime_coherent | **false** | **true** |
| auth_failures | **1** | **0** |
| child base_url | `https://chatgpt.com/backend-api/codex` | `https://api.anthropic.com` |
| child credential_class | `codex-key` | `anthropic-key` |
| child api_mode | anthropic_messages | anthropic_messages |
| invalid_tool_calls | 1 | 0 |
| wasted_tool_calls | 1 | 0 |

Honest note: a **clean** `_try_activate_fallback` on `13ce0c5c` already
rewrites parent surface attrs to Anthropic, so that path alone PASSed both
SHAs. The fixture then injects the documented split-brain (stale Codex
`base_url`/`api_key`/`_client_kwargs`, live `_anthropic_*`) and calls
`_build_child_agent`. Pre-fix inherit reads the stale surface (401-class
mismatch). #90209 snapshot reads the paired Anthropic stores.

No raw keys in artifacts.

## stale-pin-rescope (#90021)

| | Bad `13ce0c5c67` | Good `623b932007` |
|---|---|---|
| success | FAIL | PASS |
| pin key includes profile | true | false |
| unsolicited `PATCH pinned=true` after unpin | **1** (S, profile k9) | **0** |
| final S unpinned | false (backend S=true) | true (backend S=false) |
| storage keys | `.remote.<gw>.default` and `.k9` | `.remote.<gw>` only |
| state_writes | 8 | 6 |
| wasted_tool_calls (re-pins) | 1 | 0 |

Sequence: pin S on A, pin S on B, unpin S on A, switch A→B→A.

## What was not measured

Tokens, latency, provider cache hits, live `hermes -z` against a real model,
and Electron-level pin clicks. See `compression-observability.md` and
`wasted-turn-taxonomy.md`.
