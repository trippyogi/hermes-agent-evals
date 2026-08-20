# Prefix policy

Cache-eligible prefix stability is **not** a provider cache hit.
`cache_read` remains `not_observable` on the mock.

Measured on `13ce0c5c675e843af70d19c9e5144249cd51c8d1` (v0.3 probe).

| Event | Prefix expected | Observed | Evidence |
|---|---|---|---|
| Ordinary suffix turn | stable | **stable** | T1–T4 system `54ce7e5400b938bc` tools `76a7d12a8aadd424` retention 1.0 |
| Tool result append | stable previous prefix | **stable** | retention 1.0 after tool call/result suffix |
| Compression | change expected | **change** | T5 system `111dac948f37befd` retention 0.0 first divergence 0 |
| System prompt / config change | change expected | **change** | system hash `878f69714d0d9eae` retention 0.0 |
| Tool schema change | change expected | **change** | tools hash `3ad53332f066b419` (message prefix can stay; tools prefix must not) |
| Provider fallback | investigate | unmeasured | no synthetic fallback scenario |
| Delegation | separate child prefix | unmeasured | child is a different request |
| Session resume | ideally preserve compatible prefix | unmeasured | not driven this pass |

Do not add more synthetic prefix fixtures until fallback, delegation, and
resume are measured on this same instrumentation.

The probe writes the observed table into `result.extras.prefix_policy` and
the TraceV1 `model.request` policy events.
