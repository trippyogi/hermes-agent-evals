# textual_tool_protocol_failure

Version: **1**
Source: human-adjudicated `hermes-toolperf-evals/2026-08-06_rerun` episodes E07–E13
Promoted: v0.4.1

This is a component metric. Not a composite waste score. Not a Hermes
population prevalence estimate.

## Detector definition

A run/episode is a `textual_tool_protocol_failure` when all of:

1. The assistant emits recognizable tool-invocation syntax
   (JSON-like `{"name": ... "arguments": ...}` or XML `<function=...>`
   or other tool-call grammar).
2. Zero corresponding structured tool executions occur.
3. The attempted action is necessary for task progress.

Then record `likely_cause` separately:

- `provider_template`
- `model_tool_format`
- `harness_parser`
- `unknown`

Do **not** treat a positive as evidence that Hermes *planned* a wasted
turn. The episode is wasted execution from the user's perspective.

## Adjudicated evidence

| Episode | Model | Task | Arm | HUMAN_VERDICT |
|---|---|---|---|---|
| TP-2026-08-06-E07 | qwen3-coder-30b | err_big_output | baseline | waste |
| TP-2026-08-06-E08 | qwen3-coder-30b | err_big_output | baseline | waste |
| TP-2026-08-06-E09 | qwen3-coder-30b | err_inline_script | baseline | waste |
| TP-2026-08-06-E10 | qwen3-coder-30b | err_big_output | baseline | waste |
| TP-2026-08-06-E11 | qwen3-coder-30b | err_inline_script | baseline | waste |
| TP-2026-08-06-E12 | qwen3-coder-30b | err_big_output | fixes | waste |
| TP-2026-08-06-E13 | qwen3-coder-30b | err_big_output | fixes | waste |

All seven: `provider_function_xml=true`, 0 tool calls, 1 LLM turn,
abandoned, tail-oracle failure. `likely_cause` on this set: `unknown`.

W6 precision on this detected corpus: **7/7 decided = 100%**.
That is not recall and not “X% of Hermes.”

## Known limitations

- Corpus is nine induced-failure tasks, not a random production sample.
- W6 currently fires on zero structured tools plus textual syntax; it
  does not yet score `likely_cause`.
- Parallel to W3/W5 false positives: argument identity must be preserved
  in any future repeat detector. This metric does not replace those.
- Do not mix infra-startup failures into the denominator of a live-cell
  rate of this metric.

## Re-scoring

Labels live in `results/atof-waste-adjudication.json`.
TraceV1 is not modified. Detector definition changes re-score traces
against the same annotations.
