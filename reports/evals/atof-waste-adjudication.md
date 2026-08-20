# v0.4.1 — Real ATOF waste adjudication

Status: **LABELED**
Dataset: `hermes-toolperf-evals/2026-08-06_rerun`
v0.4 SHA: `ce6297df337ab0dc1abc82e6c69f842c03431451`
Harness SHA: `ce6297df337ab0dc1abc82e6c69f842c03431451`

This is a detector-validity packet, not a prevalence estimate.
Do **not** answer “how much of Hermes is wasted?”
Judge the **episode**, not the detector. Extra turns are not automatically waste.

Detector hits: **19**
Unique episodes: **13**
Overlaps collapsed: **6**
By detector: `{'W3': 6, 'W5': 6, 'W6': 7}`
Overlap distribution: `{'W3+W5': 6, 'W6': 7}`
Models: `{'anthropic/claude-sonnet-4.5': 6, 'qwen/qwen3-coder-30b-a3b-instruct': 7}`
Tasks: `{'err_multi_dir': 6, 'err_big_output': 5, 'err_inline_script': 2}`
W1 fired: **0** (retries after error usually changed arguments).

Allowed `HUMAN_VERDICT`: `waste` | `not_waste` | `unsure`.
Allowed `candidate_relationship_to_outcome`: `recovery` | `neutral` | `harmful` | `unknown`.
Leave both empty until a human fills them. Do not self-label.

Fill the JSON (`results/atof-waste-adjudication.json`) or this sheet, then return it.
Precision / KEEP-REFINE-MERGE-DROP are computed only after labels exist.

## Interesting ambiguities (not verdicts)

- **E01–E06 (W3+W5, `err_multi_dir`):** three `read_file` calls on `pkg_a` / `pkg_b` / `pkg_c` with different contents. Ingest pairing dropped arguments, so the detector saw identical null-arg retries. Decide whether this is wasted reread or parallel distinct reads. Task outcome is `unknown` (filesystem oracle).
- **E07–E13 (W6):** zero structured tools and raw `<function=...>` in the tail. Decide waste vs provider/template failure. All seven are tail-oracle **failure** and look abandoned after one LLM turn.
- **E09 / E11** are `err_inline_script`; the others in this W6 set are `err_big_output`. Same detector, two induced traps.

## Episodes

### TP-2026-08-06-E01

- model `anthropic/claude-sonnet-4.5` arm `baseline` task `err_multi_dir` rep `0` run `err_multi_dir-r0`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W3,W5` tool `read_file`
- args_changed `True` state_changed `False` error_occurred `False`
- task_outcome **unknown** (`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`)
- candidate_relationship_to_outcome: _neutral_
- turns_remaining_after_candidate `1`
- previous: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r0/proj/pkg_b/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baselin…` → `{"content": "1|0.9.7\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- current: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r0/proj/pkg_c/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baselin…` → `{"content": "1|1.4.2\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r0/proj/pkg_a/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|3.2.1\\n2|\", \"total…`
  - candidate: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r0/proj/pkg_c/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|1.4.2\\n2|\", \"total…`
  - after: `[{"name": "write_file", "arguments": {"content": "1.4.2,0.9.7,3.2.1", "path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r0/proj/versions.txt"}, "ok": true, "status": "ok", "result_summary": "{\"bytes_wr…`
- detector evidence: `{'W3': 'identical retry with unchanged state token', 'W5': 'identical read with unchanged arguments', 'episode': 'identical retry with unchanged state token'}`
- tail: `5. Create /tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r0/proj/versions.txt with comma-separated versions in order (a,b,c) 6. Reply "DONE" plus the joined string  I need to: - Read the three version.txt fil…`
- HUMAN_VERDICT: `not_waste`
- HUMAN_REASON: Distinct required read_file call with different path and new information; detector false positive caused by lost argument identity.

### TP-2026-08-06-E02

- model `anthropic/claude-sonnet-4.5` arm `baseline` task `err_multi_dir` rep `1` run `err_multi_dir-r1`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W3,W5` tool `read_file`
- args_changed `True` state_changed `False` error_occurred `False`
- task_outcome **unknown** (`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`)
- candidate_relationship_to_outcome: _neutral_
- turns_remaining_after_candidate `1`
- previous: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/pkg_a/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baselin…` → `{"content": "1|0.9.7\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- current: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/pkg_c/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baselin…` → `{"content": "1|1.4.2\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/pkg_b/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|3.2.1\\n2|\", \"total…`
  - candidate: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/pkg_c/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|1.4.2\\n2|\", \"total…`
  - after: `[{"name": "write_file", "arguments": {"content": "1.4.2,0.9.7,3.2.1", "path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/versions.txt"}, "ok": true, "status": "ok", "result_summary": "{\"bytes_wr…`
- detector evidence: `{'W3': 'identical retry with unchanged state token', 'W5': 'identical read with unchanged arguments', 'episode': 'identical retry with unchanged state token'}`
- tail: ` I'll need to: 1. Read `/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/pkg_a/version.txt` 2. Read `/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r1/proj/pkg_b/version.t…`
- HUMAN_VERDICT: `not_waste`
- HUMAN_REASON: Distinct required read_file call with different path and new information; detector false positive caused by lost argument identity.

### TP-2026-08-06-E03

- model `anthropic/claude-sonnet-4.5` arm `baseline` task `err_multi_dir` rep `2` run `err_multi_dir-r2`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W3,W5` tool `read_file`
- args_changed `True` state_changed `False` error_occurred `False`
- task_outcome **unknown** (`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`)
- candidate_relationship_to_outcome: _neutral_
- turns_remaining_after_candidate `1`
- previous: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r2/proj/pkg_c/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baselin…` → `{"content": "1|1.4.2\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- current: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r2/proj/pkg_b/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baselin…` → `{"content": "1|3.2.1\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r2/proj/pkg_a/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|0.9.7\\n2|\", \"total…`
  - candidate: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r2/proj/pkg_b/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|3.2.1\\n2|\", \"total…`
  - after: `[{"name": "write_file", "arguments": {"content": "1.4.2,0.9.7,3.2.1", "path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/baseline/err_multi_dir-r2/proj/versions.txt"}, "ok": true, "status": "ok", "result_summary": "{\"bytes_wr…`
- detector evidence: `{'W3': 'identical retry with unchanged state token', 'W5': 'identical read with unchanged arguments', 'episode': 'identical retry with unchanged state token'}`
- tail: `2. Read version.txt from pkg_a, pkg_b, and pkg_c subdirectories 3. Collect the three versions 4. Create versions.txt with the versions comma-separated in order (a,b,c) 5. Reply "DONE" plus the joined string  I should read the three version…`
- HUMAN_VERDICT: `not_waste`
- HUMAN_REASON: Distinct required read_file call with different path and new information; detector false positive caused by lost argument identity.

### TP-2026-08-06-E04

- model `anthropic/claude-sonnet-4.5` arm `fixes` task `err_multi_dir` rep `0` run `err_multi_dir-r0`
- Hermes SHA `f01c193be4aa034874ab2204c74d20e4e4360259`
- detectors: `W3,W5` tool `read_file`
- args_changed `True` state_changed `False` error_occurred `False`
- task_outcome **unknown** (`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`)
- candidate_relationship_to_outcome: _neutral_
- turns_remaining_after_candidate `1`
- previous: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r0/proj/pkg_a/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_…` → `{"content": "1|1.4.2\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- current: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r0/proj/pkg_c/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_…` → `{"content": "1|3.2.1\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r0/proj/pkg_b/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|0.9.7\\n2|\", \"total_li…`
  - candidate: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r0/proj/pkg_c/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|3.2.1\\n2|\", \"total_li…`
  - after: `[{"name": "write_file", "arguments": {"content": "1.4.2,0.9.7,3.2.1", "path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r0/proj/versions.txt"}, "ok": true, "status": "ok", "result_summary": "{\"bytes_writt…`
- detector evidence: `{'W3': 'identical retry with unchanged state token', 'W5': 'identical read with unchanged arguments', 'episode': 'identical retry with unchanged state token'}`
- tail: `4. Read the versions from each 5. Create a versions.txt file in the proj directory with the versions comma-separated in order (a,b,c) 6. Reply with "DONE" plus the joined string  I should read all three version.txt files, then create the v…`
- HUMAN_VERDICT: `not_waste`
- HUMAN_REASON: Distinct required read_file call with different path and new information; detector false positive caused by lost argument identity.

### TP-2026-08-06-E05

- model `anthropic/claude-sonnet-4.5` arm `fixes` task `err_multi_dir` rep `1` run `err_multi_dir-r1`
- Hermes SHA `f01c193be4aa034874ab2204c74d20e4e4360259`
- detectors: `W3,W5` tool `read_file`
- args_changed `True` state_changed `False` error_occurred `False`
- task_outcome **unknown** (`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`)
- candidate_relationship_to_outcome: _neutral_
- turns_remaining_after_candidate `1`
- previous: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r1/proj/pkg_b/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_…` → `{"content": "1|0.9.7\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- current: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r1/proj/pkg_c/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_…` → `{"content": "1|1.4.2\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r1/proj/pkg_a/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|3.2.1\\n2|\", \"total_li…`
  - candidate: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r1/proj/pkg_c/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|1.4.2\\n2|\", \"total_li…`
  - after: `[{"name": "write_file", "arguments": {"content": "1.4.2,0.9.7,3.2.1", "path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r1/proj/versions.txt"}, "ok": true, "status": "ok", "result_summary": "{\"bytes_writt…`
- detector evidence: `{'W3': 'identical retry with unchanged state token', 'W5': 'identical read with unchanged arguments', 'episode': 'identical retry with unchanged state token'}`
- tail: `I need to read the three version.txt files. Since these are independent reads, I can batch them together in one call.  Let me read all three files: - /tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r1/proj/pkg_a/…`
- HUMAN_VERDICT: `not_waste`
- HUMAN_REASON: Distinct required read_file call with different path and new information; detector false positive caused by lost argument identity.

### TP-2026-08-06-E06

- model `anthropic/claude-sonnet-4.5` arm `fixes` task `err_multi_dir` rep `2` run `err_multi_dir-r2`
- Hermes SHA `f01c193be4aa034874ab2204c74d20e4e4360259`
- detectors: `W3,W5` tool `read_file`
- args_changed `True` state_changed `False` error_occurred `False`
- task_outcome **unknown** (`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`)
- candidate_relationship_to_outcome: _neutral_
- turns_remaining_after_candidate `1`
- previous: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r2/proj/pkg_b/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_…` → `{"content": "1|1.4.2\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- current: `{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r2/proj/pkg_c/version.txt"}, "summary": "{\"path\": \"/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_…` → `{"content": "1|3.2.1\n2|", "total_lines": 1, "file_size": 6, "truncated": false, "is_binary": false, "is_image": false}`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r2/proj/pkg_a/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|0.9.7\\n2|\", \"total_li…`
  - candidate: `[{"name": "read_file", "arguments": {"path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r2/proj/pkg_c/version.txt"}, "ok": true, "status": "ok", "result_summary": "{\"content\": \"1|3.2.1\\n2|\", \"total_li…`
  - after: `[{"name": "write_file", "arguments": {"content": "1.4.2,0.9.7,3.2.1", "path": "/tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r2/proj/versions.txt"}, "ok": true, "status": "ok", "result_summary": "{\"bytes_writt…`
- detector evidence: `{'W3': 'identical retry with unchanged state token', 'W5': 'identical read with unchanged arguments', 'episode': 'identical retry with unchanged state token'}`
- tail: `I need to read three files and then write one file. These are independent read operations, so I can batch them together.  The paths would be: - /tmp/abeval-workspace/runs/anthropic_claude-sonnet-4.5/fixes/err_multi_dir-r2/proj/pkg_a/versio…`
- HUMAN_VERDICT: `not_waste`
- HUMAN_REASON: Distinct required read_file call with different path and new information; detector false positive caused by lost argument identity.

### TP-2026-08-06-E07

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `baseline` task `err_big_output` rep `0` run `err_big_output-r0`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3…` → `I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r0/proj/noi…`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r0/proj/noi…`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

### TP-2026-08-06-E08

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `baseline` task `err_big_output` rep `1` run `err_big_output-r1`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseli…` → `I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r1/proj/noisy_build.py </par…`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-in…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r1/proj/noisy_build.py </par…`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

### TP-2026-08-06-E09

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `baseline` task `err_inline_script` rep `1` run `err_inline_script-r1`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll compute the sum of squares of the first 4000 integers using a single inline Python one-liner.  <function=terminal> <parameter=command> python3 -c \"print(sum(i**2 for i in range(1, 4001)))…` → `I'll compute the sum of squares of the first 4000 integers using a single inline Python one-liner.  <function=terminal> <parameter=command> python3 -c "print(sum(i**2 for i in range(1, 4001)))" </parameter>`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll compute the sum of squares of the first 4000 integers using a single inline Python one-liner.  <function=terminal> <parameter=command> python3 -c \"print(sum(i**2 for i in ran…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll compute the sum of squares of the first 4000 integers using a single inline Python one-liner.  <function=terminal> <parameter=command> python3 -c "print(sum(i**2 for i in range(1, 4001)))" </parameter>`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

### TP-2026-08-06-E10

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `baseline` task `err_big_output` rep `2` run `err_big_output-r2`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseli…` → `I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r2/proj/noisy_build.py </par…`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-in…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll run the Python script and look for the UNIQUE_TOKEN line in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/baseline/err_big_output-r2/proj/noisy_build.py </par…`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

### TP-2026-08-06-E11

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `baseline` task `err_inline_script` rep `2` run `err_inline_script-r2`
- Hermes SHA `5b4d20b524c641a3c7a708a5dc8696a4c6a28588`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll compute the sum of squares of the first 4000 integers using a single inline python3 -c one-liner.  <function=terminal> <parameter=command> python3 -c \"print(sum(i**2 for i in range(1, 400…` → `I'll compute the sum of squares of the first 4000 integers using a single inline python3 -c one-liner.  <function=terminal> <parameter=command> python3 -c "print(sum(i**2 for i in range(1, 4001)))" </parameter>`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll compute the sum of squares of the first 4000 integers using a single inline python3 -c one-liner.  <function=terminal> <parameter=command> python3 -c \"print(sum(i**2 for i in…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll compute the sum of squares of the first 4000 integers using a single inline python3 -c one-liner.  <function=terminal> <parameter=command> python3 -c "print(sum(i**2 for i in range(1, 4001)))" </parameter>`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

### TP-2026-08-06-E12

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `fixes` task `err_big_output` rep `0` run `err_big_output-r0`
- Hermes SHA `f01c193be4aa034874ab2204c74d20e4e4360259`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3…` → `I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r0/proj/noisy_…`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r0/proj/noisy_…`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

### TP-2026-08-06-E13

- model `qwen/qwen3-coder-30b-a3b-instruct` arm `fixes` task `err_big_output` rep `1` run `err_big_output-r1`
- Hermes SHA `f01c193be4aa034874ab2204c74d20e4e4360259`
- detectors: `W6` tool `None`
- args_changed `False` state_changed `False` error_occurred `False`
- task_outcome **failure** (`reconstructed_from_tail`)
- candidate_relationship_to_outcome: _harmful_
- turns_remaining_after_candidate `0`
- previous: `{"name": "openrouter", "arguments": null, "summary": "model.response"}` → `model.response`
- current: `{"name": null, "arguments": null, "summary": "I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3…` → `I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r1/proj/noisy_…`
- trajectory (1–2 before / candidate / 1–2 after):
  - before: `[{"role": "llm", "name": "openrouter", "summary": "model.response"}]`
  - candidate: `[{"name": null, "role": "textual_pseudo_call", "summary": "I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3…`
  - after: `[]`
- detector evidence: `{'W6': 'transcript contains a JSON/XML tool call and events have zero structured tools', 'episode': 'transcript contains a JSON/XML tool call and events have zero structured tools'}`
- tail: `I'll run the Python script and look for the line starting with 'UNIQUE_TOKEN=' in its output.  <function=terminal> <parameter=command> python3 /tmp/abeval-workspace/runs/qwen_qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r1/proj/noisy_…`
- HUMAN_VERDICT: `waste`
- HUMAN_REASON: Textual pseudo-tool call consumed the model turn, no structured tool executed, and the task terminated unsuccessfully. Root cause may be provider/chat-template/tool-protocol formatting rather than agent planning; classify the episode as harmful execution waste without attributing cause to Hermes.

## Next gate

Labels are complete. Validity report: `reports/evals/v0.4.1-atof-waste-validity.md`.
Do not compute recall or population prevalence. No composite waste score.

