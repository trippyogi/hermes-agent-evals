# First results — v0.1 revalidation

**Date:** 2026-08-19  
**Harness SHA:** `637af5d47d5bb73fc3bfc9adfee47d91c2b7a212`  
**Fixture schema:** 2  
**Command:**

```
python -m hermes_eval compare --historical --suite core-failures --out results/compare-core-failures-historical-v0.1
```

**Gate: PASSED — 3 / 3 distinguished and identical to frozen expected splits.**

Machine-readable: `results/compare-core-failures-historical-v0.1/compare.json`  
Frozen expected: `evals/provenance/expected-historical.json`  
SHA provenance: `evals/provenance/manifest.json`

## Historical splits (identical to v0.1 freeze)

| Fixture | Bad SHA | Good SHA | Bad | Good | Split identical? |
|---|---|---|---|---|---|
| zero-toolset | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` | `ed5b9152ce975ada68f0b53a21c4806f29ed0852` | FAIL (`warning_emitted=false`) | PASS (`warning_emitted=true`) | yes |
| delegate-fallback-runtime | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` | `c6a2fb48af74e3c795015aeb6e615733a9b5bac5` | FAIL (`runtime_coherent=false`, `auth_failures=1`) | PASS (`runtime_coherent=true`, `auth_failures=0`) | yes |
| stale-pin-rescope | `13ce0c5c675e843af70d19c9e5144249cd51c8d1` | `623b93200779d31d416eb2c5f9116106de6f5adb` | FAIL (1 unsolicited PATCH, backend S=true) | PASS (0 unsolicited PATCH, S unpinned) | yes |

Delegate fixture remains **fault-injected**. Clean fallback on the bad SHA still does not naturally produce the discriminator.

Every result JSON on this run records `harness_sha=637af5d47d5bb73fc3bfc9adfee47d91c2b7a212`, `harness_dirty=false`, `fixture_version`, `fixture_schema_version=2`, and full Hermes SHAs.

## Live behavior

**BLOCKED.** `HERMES_EVAL_API_KEY`, `HERMES_EVAL_PROVIDER`, and `HERMES_EVAL_MODEL` were unset. The runner did not read `~/.hermes` and did not substitute synthetic rates.

Artifact: `results/zero-toolset-live/result.json` (`status=BLOCKED`).

## Prefix observability

Probe succeeded (`success=true`) against `13ce0c5c675e843af70d19c9e5144249cd51c8d1`.

Measurable on the wrapped request path:

- `system_prompt_hash` — stable across non-compress turns (`54ce7e5400b938bc`)
- `tool_schema_hash` — stable (`76a7d12a8aadd424`)
- `stable_message_prefix_hash` / `message_count`
- mock `input_tokens` / `output_tokens` / `cache_read_tokens=0`
- `compress()` fired (`after_count=12`) and changed `system_prompt_hash` to `111dac948f37befd`

Honest limit: this probe called `run_conversation` as separate 2-message turns (`message_count=2`), so `stable_message_prefix_hash` of k=2 tracks the current user text rather than an accumulating session prefix. System + tool schema hashes still detect unexpected prompt/toolset churn. Provider cache hits remain `not_observable` without live credentials.

## Waste taxonomy

50 unlabeled candidates (W1=8, W2=6, W3=19, W4=7, W5=3, W6=7).

Sheet: `reports/evals/wasted-turn-labeling-sample.md`  
JSON: `results/wasted-turn-scan.json`

W1 and W3 often fire on the same event; that is intentional overlap for human adjudication. Not an automatic score.
