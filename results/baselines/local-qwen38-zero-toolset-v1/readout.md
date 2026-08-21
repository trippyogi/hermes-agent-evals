# local-qwen38-zero-toolset-v1

Frozen local-live baseline. Do not overwrite; create a new experiment identity for future runs.

## Outcome and observability

- CONTROL: 10/10 success; 10 structured tool calls; 10 matching results.
- FAULT: 0/10 success; 0 structured tool calls; 0 results.
- Infrastructure failures: 0.
- TraceV1 errors or runner disagreements: 0.

## FAULT terminal behavior

- `textual_tool_protocol_failure`: 0/10, Wilson 95% CI 0.0000–0.2775.
- `other_tool_like_text`: 3/10 (`fault:0`, `fault:1`, `fault:2`), CI 0.1078–0.6032.
- `hallucinated_completion`: 3/10 (`fault:3`, `fault:5`, `fault:7`), CI 0.1078–0.6032.
- `explicit_capability_failure`: 0/10, CI 0.0000–0.2775.
- `remediation_or_user_request`: 0/10, CI 0.0000–0.2775.
- `plain_failure_other`: 4/10 (`fault:4`, `fault:6`, `fault:8`, `fault:9`), CI 0.1682–0.6873.

The three terminal buckets above are mutually exclusive for this readout. The reusable component metrics remain independently reportable.

## Historical textual-tool comparison

`NOT_OBSERVED`. The Qwen3-Coder E07–E13 episodes emitted recognizable raw `<function=...>` invocation syntax with zero structured execution. No CONTROL or FAULT episode in this local Qwen3.8 cell emitted recognizable JSON/XML/other tool-call grammar. The broader failure context is related—required action, zero execution—but the adjudicated textual protocol failure shape is absent. Prevalence is not compared across corpora.

## CONTROL efficiency, successful runs only

- Turns: median 2.0, IQR 0.0.
- Tool calls: median 1.0, IQR 0.0.
- Input tokens: median 13,656.5, IQR 11.25.
- Output tokens: median 114.0, IQR 4.75.
- Total tokens: median 27,249.5, IQR 15.25.
- Cache read: median 13,480.0, IQR 9.5.
- Cache write: median 0.0, IQR 0.0.
- Duration: median 8,100.9 ms, IQR 90.775 ms.

## FAULT failure cost

- Turns: median 1.0, IQR 0.75.
- Input tokens: median 514.0, IQR 3.5.
- Output tokens: median 36.5, IQR 82.0.
- Total tokens: median 709.0, IQR 584.0.
- Cache read: median 159.0, IQR 501.0.
- Cache write: median 0.0, IQR 0.0.
- Duration: median 3,174.85 ms, IQR 6,497.15 ms.

Lower failure cost is not interpreted as better agent quality.

## Readiness

Hermes Behavioral Observatory: **MINIMUM VIABLE READY**.

It can compare Hermes revisions/configurations on repeated live behavior, measure outcomes and success-conditional efficiency and failure components, and ingest/re-score external traces later.

It is not yet representative of all Hermes usage, statistically mature, multi-model, a multi-task behavioral suite, a population prevalence estimator, or a cross-harness benchmark.
