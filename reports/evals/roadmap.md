# Roadmap

Two products:

1. **Hermes Regression Canary** — cheap, deterministic, commit-level.
   **READY** with a 3/3 historical gate. Expand only through the full fixture
   admission gate.
2. **Hermes Behavioral Observatory** — slower, repeated model runs.
   **RESEARCH READY.** Two local model routes and two immutable Hermes
   treatments have repeated N=10 cells with re-scoreable failure modes and
   coherent external-oracle, state.db, and TraceV1 evidence.

| Milestone | Goal | Main output | Gate |
|---|---|---|---|
| v0.3 Trace spine | Neutral representation | TraceV1 + adapters + re-scoring | Existing 3 fixtures reproduce from trace |
| v0.3.1 Toolperf ingestion | External validation | 108-run ATOF archive → TraceV1 | Metric identity vs abeval; no new fixtures |
| v0.4 Behavioral statistics | Stochastic behavior | Frozen Qwen3.8 live baseline + policy | Wilson / efficiency-given-success / coherent tool evidence |
| v0.4.1 Waste adjudication | Label real ATOF waste | 13 episodes labeled; W6 kept as protocol failure | Precision among decided; textual_tool_protocol_failure v1 |
| v0.5 Controlled matrix | Separate treatment and model-route observations | Two-model × two-treatment frozen matrix | Behavioral Observatory RESEARCH READY |
| v0.6 Production corpus | Mine real Hermes behavior safely | Manifests, sanitizer, EpisodeV1, adjudication, candidates, advisory bridge | 30–60 labels; privacy and admission gates; ≤2 promotions |
| v0.7 Server isolation | Separate model from serving stack | Same model × two servers | Valid controlled two-server comparison |
| v0.8 State contracts | General state/frame-condition scoring | StateTaskV1 + three converted fixtures | Historical behavior unchanged |
| v0.9 External beta | Test team usability | NousResearch external research beta | Independent Quick/live/PR feedback |
| v1.0 Production external observatory | Reproducible engineering evidence | Versioned contracts, operations, bundles, advisory bridge | All hard release gates |

v0.6 does not add fixtures before human adjudication, modify Hermes or
NousResearch repositories, create a leaderboard, or change GitWorthy verdict
or ranking behavior.

v0.4 measurements (when live RUN exists and CONTROL is valid):

- `control_task_success_rate` + Wilson 95% CI
- `fault_task_success_rate` + CI (expect ≈ 0)
- `fault_textual_pseudo_tool_call` split: JSON-like / XML `<function=...>` / other
- `fault_hallucinated_completion_rate`
- `fault_explicit_capability_failure_rate`
- `fault_diagnostic_rate`
- efficiency **given CONTROL success**: median/IQR turns, tool calls, tokens, duration
- failure cost on failed runs
- N, min/max

Do not add pass@k until N supports it. No composite score.

Fault-arm **task success stays ~0**. Known-good is loud, not tool restoration.

## Active v0.6 sequence

1. Synchronize public status and freeze v0.5 provenance.
2. Add CorpusManifestV1, EpisodeV1, advisory GitWorthy contracts, and deterministic redaction.
3. Ingest toolperf plus frozen local v0.4/v0.5 corpora.
4. Mine 30–60 unique episodes and stop for human labels.
5. Produce 3–5 candidate cards; promote at most two only after all admission gates pass.
6. Re-run deterministic 3/3, ATOF 108/108, and frozen v0.5 re-scoring.

Do not begin v0.7 until every v0.6 acceptance gate is green.
