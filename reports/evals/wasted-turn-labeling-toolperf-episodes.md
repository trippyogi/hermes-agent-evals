# Wasted-turn labeling sample (episodes)

Do **not** train an automatic score from this sheet.
Label **episodes**, not raw detector hits. W1+W3 on the same retry is one decision.
Fill `HUMAN_VERDICT` with waste / not-waste / unsure.

REAL_ATOF_DATA: available
Corpus: atof
Detector hits: 19
Unique episodes: 13
Overlaps collapsed: 6
Hit labels: {'W3': 6, 'W5': 6, 'W6': 7}

| # | w_labels | tool | source | index | hits | state_changed | evidence | HUMAN_VERDICT |
|---|---|---|---|---|---|---|---|---|
| 1 | W3,W5 | `read_file` | `anthropic/claude-sonnet-4.5/baseline/err_multi_dir-r0` | 2 | 2 | False | identical retry with unchanged state token | |
| 2 | W3,W5 | `read_file` | `anthropic/claude-sonnet-4.5/baseline/err_multi_dir-r1` | 2 | 2 | False | identical retry with unchanged state token | |
| 3 | W3,W5 | `read_file` | `anthropic/claude-sonnet-4.5/baseline/err_multi_dir-r2` | 2 | 2 | False | identical retry with unchanged state token | |
| 4 | W3,W5 | `read_file` | `anthropic/claude-sonnet-4.5/fixes/err_multi_dir-r0` | 2 | 2 | False | identical retry with unchanged state token | |
| 5 | W3,W5 | `read_file` | `anthropic/claude-sonnet-4.5/fixes/err_multi_dir-r1` | 2 | 2 | False | identical retry with unchanged state token | |
| 6 | W3,W5 | `read_file` | `anthropic/claude-sonnet-4.5/fixes/err_multi_dir-r2` | 2 | 2 | False | identical retry with unchanged state token | |
| 7 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r0` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 8 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r1` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 9 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/baseline/err_inline_script-r1` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 10 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r2` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 11 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/baseline/err_inline_script-r2` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 12 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r0` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |
| 13 | W6 | `` | `qwen/qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r1` | None | 1 | False | transcript contains a JSON/XML tool call and events have zero structured tools | |

