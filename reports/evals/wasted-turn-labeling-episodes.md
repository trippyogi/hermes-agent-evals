# Wasted-turn labeling sample (episodes)

Do **not** train an automatic score from this sheet.
Label **episodes**, not raw detector hits. W1+W3 on the same retry is one decision.
Fill `HUMAN_VERDICT` with waste / not-waste / unsure.

**Harness:** `e7b6caa11755e795d98d9c37807c4006a497fed2`  
**REAL_ATOF_DATA:** BLOCKED  
**Corpus:** scrubbed_reconstruction  
**Detector hits:** 50  
**Unique episodes:** 38  
**Overlaps collapsed:** 11  
**Hit labels:** W1=8, W2=6, W3=19, W4=7, W5=3, W6=7

Machine JSON with full sources: clone run `results/wasted-turn-scan.json` (gitignored).

| # | w_labels | tool | source | index | hits | state_changed | evidence | HUMAN_VERDICT |
|---|---|---|---|---|---|---|---|---|
| 1 | W6 | `` | `evals/fixtures/_waste_samples/empty-toolset-text.json` |  | 1 | false | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 2 | W1,W3 | `terminal` | `evals/fixtures/_waste_samples/retry-after-error.json` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 3 | W1,W3 | `terminal` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:1` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 4 | W1,W3 | `terminal` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:2` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 5 | W1,W3 | `terminal` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:3` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 6 | W4 | `patch` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:4` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 7 | W1,W3 | `patch` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:4` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 8 | W3 | `terminal` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:5` | 1 | 1 | false | identical retry with unchanged state token | |
| 9 | W3 | `execute_code` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:6` | 1 | 1 | false | identical retry with unchanged state token | |
| 10 | W3 | `process` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:7` | 1 | 1 | false | identical retry with unchanged state token | |
| 11 | W3 | `process` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:7` | 2 | 1 | false | identical retry with unchanged state token | |
| 12 | W3 | `process` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:8` | 1 | 1 | false | identical retry with unchanged state token | |
| 13 | W2 | `session_resume` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:9` | 0 | 1 | false | event marked dead_runtime/session_dead | |
| 14 | W2 | `session_resume` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:10` | 0 | 1 | false | event marked dead_runtime/session_dead | |
| 15 | W2 | `delegate_task` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:11` | 0 | 1 | false | event marked dead_runtime/session_dead | |
| 16 | W2 | `terminal` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:12` | 0 | 1 | false | event marked dead_runtime/session_dead | |
| 17 | W4 | `write_file` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:13` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 18 | W4 | `write_file` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:14` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 19 | W4 | `pin` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:15` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 20 | W4 | `patch` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:16` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 21 | W3,W5 | `read_file` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:17` | 1 | 2 | false | identical retry with unchanged state token | |
| 22 | W3,W5 | `read_file` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:18` | 1 | 2 | false | identical retry with unchanged state token | |
| 23 | W3,W5 | `read` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:20` | 1 | 2 | false | identical retry with unchanged state token | |
| 24 | W6 | `` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:21` |  | 1 | false | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 25 | W6 | `` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:22` |  | 1 | false | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 26 | W6 | `` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:23` |  | 1 | false | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 27 | W6 | `` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:24` |  | 1 | false | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 28 | W6 | `` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:25` | 0 | 1 | false | assistant text matches a tool-call shape and no structured tool event in this slice | |
| 29 | W6 | `` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:26` | 0 | 1 | false | assistant text matches a tool-call shape and no structured tool event in this slice | |
| 30 | W1,W3 | `terminal` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:27` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 31 | W4 | `patch` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:28` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 32 | W1,W3 | `patch` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:28` | 1 | 2 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
| 33 | W3 | `search_files` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:29` | 1 | 1 | false | identical retry with unchanged state token | |
| 34 | W3 | `search_files` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:30` | 1 | 1 | false | identical retry with unchanged state token | |
| 35 | W4 | `write_file` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:31` | 0 | 1 | true | tool result immediately inverted by the next tool | |
| 36 | W3 | `write_file` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:31` | 1 | 1 | false | identical retry with unchanged state token | |
| 37 | W2 | `session_resume` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:32` | 0 | 1 | false | event marked dead_runtime/session_dead | |
| 38 | W1,W3,W2 | `session_resume` | `evals/fixtures/_waste_samples/labeling-corpus.jsonl:32` | 1 | 3 | false | same name+args after a deterministic-looking failure, no recorded intervening state change | |
