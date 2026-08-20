# Wasted-turn taxonomy (conservative)

Do **not** treat parser hits as objective waste. Every event is a **candidate**
for human labeling.

Mined from Teknium’s 400k-message window (`hermes-toolperf-evals/analysis/CANDIDATES.md`)
plus the failure classes in this harness. The parser never opens `~/.hermes`.

## Patterns (candidate only)

| ID | Pattern | Why it *might* be waste | Why it might be fine | Confidence default |
|---|---|---|---|---|
| W1 | Repeat identical tool after deterministic failure | Same name+args, no recorded state change | Model probing a flaky env; first error was transient | medium |
| W2 | Tool against known-dead runtime/session | Resume of a reaped id cannot succeed | UI has not yet received reclaim | high if tagged dead |
| W3 | Retry with no intervening state change | Duplicate poll/read | Output may have changed off-record | low–medium |
| W4 | Tool immediately undone | write then delete; pin then unpin in one turn | Explicit user correction | medium |
| W5 | Repeated identical read | Second read of same path/offset | File changed; pagination | low |
| W6 | Empty-tool schema then textual pseudo-call | No tool ran; model dumped JSON | Model cannot use tools even when schemas exist — check control arm | high when schemas==0 |

## What we will not auto-score as waste

- Any single failed tool call
- `cd X &&` prefixes (P1 in toolperf — high frequency, needs ATOF + success)
- Truncated `read_file` follow-ups (often necessary)
- Weak-model extra turns that eventually succeed

## Parser

```
python -m hermes_eval scan-waste evals/fixtures/_waste_samples --out results/wasted-turn-scan.json --label-sheet
```

Label sheet columns: W1–W6, evidence, state_changed, previous_result_hash,
HUMAN_VERDICT blank. Do not train/derive an automatic score from this sheet.

Production ATOF traces were not in `hermes-toolperf-evals/results` (only
`meta.jsonl` tails). The v0.1 labeling sample is **scrubbed reconstructions**
from `analysis/CANDIDATES.md`, toolperf corpus fixtures, and harness
samples — marked `source_class` accordingly.
