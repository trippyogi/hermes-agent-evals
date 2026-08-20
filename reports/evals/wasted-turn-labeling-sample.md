# Wasted-turn labeling sample (v0.1)

Do **not** train an automatic score from this sheet.
Fill `HUMAN_VERDICT` with `waste` / `not-waste` / `unsure`.

**Harness:** `637af5d47d5bb73fc3bfc9adfee47d91c2b7a212`  
**Candidates:** 50  
**By label:** W1=8, W2=6, W3=19, W4=7, W5=3, W6=7

Production ATOF traces were not present under `hermes-toolperf-evals/results`
(only `meta.jsonl` tails). This sample is scrubbed reconstructions from
`analysis/CANDIDATES.md`, toolperf corpus fixtures, and harness samples.
JSON with `previous_result_hash` and full source paths:
`results/wasted-turn-scan.json`.

W1 and W3 often fire together on the same retry. That overlap is for
human adjudication.

| # | W | tool | source | state_changed | evidence | HUMAN_VERDICT |
|---|---|---|---|---|---|---|
| 1 | W6 | | `_waste_samples/empty-toolset-text.json` | false | JSON/XML tool call in transcript; zero structured tools | |
| 2 | W1 | terminal | `_waste_samples/retry-after-error.json` | false | identical name+args after deterministic failure | |
| 3 | W3 | terminal | `_waste_samples/retry-after-error.json` | false | identical retry, no state-token change | |
| 4 | W1 | terminal | `labeling-corpus.jsonl:1` | false | python: command not found, identical retry | |
| 5 | W3 | terminal | `labeling-corpus.jsonl:1` | false | identical retry, no state-token change | |
| 6 | W1 | terminal | `labeling-corpus.jsonl:2` | false | python: command not found, identical retry | |
| 7 | W3 | terminal | `labeling-corpus.jsonl:2` | false | identical retry, no state-token change | |
| 8 | W1 | terminal | `labeling-corpus.jsonl:3` | false | gh Unknown JSON field, identical retry | |
| 9 | W3 | terminal | `labeling-corpus.jsonl:3` | false | identical retry, no state-token change | |
| 10 | W4 | patch | `labeling-corpus.jsonl:4` | true | patch immediately inverted by next tool | |
| 11 | W1 | patch | `labeling-corpus.jsonl:4` | false | identical old/new patch error retry | |
| 12 | W3 | patch | `labeling-corpus.jsonl:4` | false | identical retry, no state-token change | |
| 13 | W3 | terminal | `labeling-corpus.jsonl:5` | false | duplicate `ls` with same cwd | |
| 14 | W3 | execute_code | `labeling-corpus.jsonl:6` | false | duplicate execute_code | |
| 15 | W3 | process | `labeling-corpus.jsonl:7` | false | duplicate process poll | |
| 16 | W3 | process | `labeling-corpus.jsonl:7` | false | second duplicate process poll | |
| 17 | W3 | process | `labeling-corpus.jsonl:8` | false | duplicate process wait | |
| 18 | W2 | session_resume | `labeling-corpus.jsonl:9` | false | dead_runtime tagged | |
| 19 | W2 | session_resume | `labeling-corpus.jsonl:10` | false | session_dead tagged | |
| 20 | W2 | delegate_task | `labeling-corpus.jsonl:11` | false | dead_runtime tagged | |
| 21 | W2 | terminal | `labeling-corpus.jsonl:12` | false | dead_runtime tagged | |
| 22 | W4 | write_file | `labeling-corpus.jsonl:13` | true | write then delete_file | |
| 23 | W4 | write_file | `labeling-corpus.jsonl:14` | true | write then delete_file | |
| 24 | W4 | pin | `labeling-corpus.jsonl:15` | true | pin then unpin | |
| 25 | W4 | patch | `labeling-corpus.jsonl:16` | true | tagged immediately_undone | |
| 26 | W3 | read_file | `labeling-corpus.jsonl:17` | false | identical read retry | |
| 27 | W5 | read_file | `labeling-corpus.jsonl:17` | false | repeated identical read | |
| 28 | W3 | read_file | `labeling-corpus.jsonl:18` | false | identical read retry | |
| 29 | W5 | read_file | `labeling-corpus.jsonl:18` | false | repeated identical read | |
| 30 | W3 | read | `labeling-corpus.jsonl:20` | false | identical read retry | |
| 31 | W5 | read | `labeling-corpus.jsonl:20` | false | repeated identical read | |
| 32 | W6 | | `labeling-corpus.jsonl:21` | false | empty events + JSON tool-call transcript | |
| 33 | W6 | | `labeling-corpus.jsonl:22` | false | `<function=terminal>` in transcript, no tools | |
| 34 | W6 | | `labeling-corpus.jsonl:23` | false | `<function=terminal>` in transcript, no tools | |
| 35 | W6 | | `labeling-corpus.jsonl:24` | false | JSON write_file in transcript, no tools | |
| 36 | W6 | | `labeling-corpus.jsonl:25` | false | assistant text JSON tool call | |
| 37 | W6 | | `labeling-corpus.jsonl:26` | false | assistant `<function=write_file>` | |
| 38 | W1 | terminal | `labeling-corpus.jsonl:27` | false | ModuleNotFoundError identical retry | |
| 39 | W3 | terminal | `labeling-corpus.jsonl:27` | false | identical retry, no state-token change | |
| 40 | W4 | patch | `labeling-corpus.jsonl:28` | true | failed patch tagged inverted | |
| 41 | W1 | patch | `labeling-corpus.jsonl:28` | false | hunk-not-found identical retry | |
| 42 | W3 | patch | `labeling-corpus.jsonl:28` | false | identical retry, no state-token change | |
| 43 | W3 | search_files | `labeling-corpus.jsonl:29` | false | zero-match search repeated | |
| 44 | W3 | search_files | `labeling-corpus.jsonl:30` | false | duplicate SECRET_ROTATION_KEY search | |
| 45 | W4 | write_file | `labeling-corpus.jsonl:31` | true | write then identical rewrite | |
| 46 | W3 | write_file | `labeling-corpus.jsonl:31` | false | identical write retry | |
| 47 | W2 | session_resume | `labeling-corpus.jsonl:32` | false | dead_runtime tagged | |
| 48 | W1 | session_resume | `labeling-corpus.jsonl:32` | false | dead session identical retry | |
| 49 | W3 | session_resume | `labeling-corpus.jsonl:32` | false | identical retry, no state-token change | |
| 50 | W2 | session_resume | `labeling-corpus.jsonl:32` | false | dead_runtime on retry | |
