"""v0.4 behavioral analysis: live cell + toolperf sanity. No composite score.

Outcome first; efficiency is computed only given success.
Does not add pass@k — N=10 is too small for a meaningful estimate.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from hermes_eval.behavior import (
    ESCALATE_N,
    MIN_N_FOR_RATE,
    PREFERRED_N,
    behavioral_rows,
    control_cell_validity,
    efficiency_given_success,
    failure_cost,
    failure_mode_distribution,
    reportable_rate,
)
from hermes_eval.gitutil import REPO_ROOT
from hermes_eval.stats import summarize_continuous, wilson_interval
from hermes_eval.trace.adapters.native import emit_live_run
from hermes_eval.trace.model import validate_trace
from hermes_eval.trace.rescore import score_trace

QWEN = "qwen/qwen3-coder-30b-a3b-instruct"
RECOVERY_TASKS = ("err_inline_script", "err_big_output", "err_big_file_read")
EFFICIENCY_TASK = "err_case_search"


def analyze_live_result(result: dict[str, Any]) -> dict[str, Any]:
    """Analyze a zero-toolset-live result.json. Never invents rates if BLOCKED."""
    extras = result.get("extras") or {}
    status = result.get("status") or ("BLOCKED" if extras.get("blocked_reason") else "UNKNOWN")
    if status == "BLOCKED":
        return {
            "status": "BLOCKED",
            "blocked_reason": extras.get("blocked_reason") or "missing HERMES_EVAL_*",
            "synthetic_substitution": False,
            "cell_valid_for_fault_comparison": False,
            "control": None,
            "fault": None,
            "trace_integrity": _trace_integrity(result, []),
            "historical_warning_comparison": "skipped_live_blocked",
            "observatory": "NOT READY",
        }
    control_all = list(extras.get("control_runs") or [])
    fault_all = list(extras.get("fault_runs") or [])
    control = behavioral_rows(control_all)
    fault = behavioral_rows(fault_all)
    c_ok = sum(1 for r in control if r.get("task_success"))
    f_ok = sum(1 for r in fault if r.get("task_success"))
    validity = control_cell_validity(c_ok, len(control))
    control_block = {
        "n": len(control),
        "n_infra_startup": len(control_all) - len(control),
        "success": reportable_rate(c_ok, len(control)),
        "validity": validity,
        "efficiency_given_success": efficiency_given_success(control),
        "failure_cost": failure_cost(control),
        "execution_all_runs": _execution_all(control),
    }
    fault_block = {
        "n": len(fault),
        "n_infra_startup": len(fault_all) - len(fault),
        "success": reportable_rate(f_ok, len(fault)),
        "failure_modes": failure_mode_distribution(fault),
        "efficiency_given_success": efficiency_given_success(fault),
        "failure_cost": failure_cost(fault),
        "execution_all_runs": _execution_all(fault),
        "note": (
            "Fault-arm task success is expected ~0. Known-good makes an empty "
            "toolset loud; it does not restore tools. Infra-startup rows are "
            "excluded from these denominators."
        ),
    }
    traces = _per_run_traces(result, control_all, fault_all)
    integrity = _trace_integrity(result, traces)
    return {
        "status": "RUN",
        "synthetic_substitution": False,
        "cell_valid_for_fault_comparison": bool(validity.get("valid")),
        "model": result.get("model") or extras.get("model"),
        "provider": result.get("provider") or extras.get("provider"),
        "params": extras.get("model_params") or extras.get("params"),
        "hermes_ref": result.get("hermes_ref"),
        "harness_sha": result.get("harness_sha"),
        "reps": extras.get("reps") or len(control),
        "control": control_block,
        "fault": None if not validity.get("valid") else fault_block,
        "fault_raw": fault_block,
        "invalid_reason": None if validity.get("valid") else validity.get("reason"),
        "recommend_n": validity.get("recommend_n"),
        "trace_integrity": integrity,
        "historical_warning_comparison": "skipped_until_primary_cell_valid",
        "pass_at_k": "not_computed_n_too_small",
        "observatory": "NOT READY",
    }


def _execution_all(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "turns": summarize_continuous(r.get("turns") for r in rows),
        "actual_tool_calls": summarize_continuous(r.get("actual_tool_calls") for r in rows),
        "successful_tool_calls": summarize_continuous(r.get("successful_tool_calls") for r in rows),
        "failed_tool_calls": summarize_continuous(r.get("failed_tool_calls") for r in rows),
        "retries_after_error": summarize_continuous(r.get("retries_after_error") for r in rows),
        "identical_retries_after_error": summarize_continuous(
            r.get("identical_retries_after_error") for r in rows
        ),
        "duration_ms": summarize_continuous(r.get("duration_ms") for r in rows),
        "total_tokens": summarize_continuous(r.get("total_tokens") for r in rows),
    }


def _per_run_traces(
    result: dict[str, Any], control: list[dict], fault: list[dict]
) -> list[dict[str, Any]]:
    traces = []
    for i, row in enumerate(control):
        traces.append(emit_live_run(result, row, arm="control", index=i))
    for i, row in enumerate(fault):
        traces.append(emit_live_run(result, row, arm="fault", index=i))
    return traces


def _trace_integrity(result: dict[str, Any], traces: list[dict[str, Any]]) -> dict[str, Any]:
    from hermes_eval.trace.adapters.native import emit_native

    aggregate = emit_native(result)
    agg_errors = validate_trace(aggregate)
    n_valid = 0
    n_rescored = 0
    disagreements = 0
    missing: list[str] = []
    required_types = {
        "model.request",
        "model.response",
        "final.output",
    }
    for trace in traces:
        errors = validate_trace(trace)
        if not errors:
            n_valid += 1
        types = {e.get("type") for e in (trace.get("events") or [])}
        if not required_types.issubset(types):
            missing.append(
                f"{trace.get('run_id')}: missing {sorted(required_types - types)}"
            )
        scored = score_trace(trace)
        n_rescored += 1
        final = (trace.get("final_state") or {}).get("task_success")
        runner_ok = (trace.get("final_state") or {}).get("runner_task_success")
        if runner_ok is not None and final is not None and bool(runner_ok) != bool(final):
            disagreements += 1
        if scored.get("notes") and any("no TraceV1 scorer" in str(n) for n in scored.get("notes") or []):
            disagreements += 1
    return {
        "n_run_traces": len(traces),
        "n_valid": n_valid,
        "n_rescored": n_rescored,
        "disagreements": disagreements,
        "aggregate_errors": agg_errors,
        "missing_telemetry": missing[:20],
        "schema_gaps": _schema_gaps_documented(),
    }


def _schema_gaps_documented() -> list[str]:
    return [
        (
            "oneshot usage.json does not emit per-turn model.request bodies; "
            "TraceV1 records a single request/response span per arm with "
            "token totals, not a full chat log. Representable with existing "
            "model.request / model.response events."
        ),
        (
            "Session artifacts under HERMES_HOME are best-effort; some "
            "oneshot runs leave no structured tool.call events. Counts then "
            "come from usage/api_calls. Existing tool.call / tool.result "
            "events still represent the concept when artifacts exist."
        ),
        (
            "Cache read/write tokens are provider-optional. Stored in "
            "metrics / final.output when present; otherwise not_observable."
        ),
        (
            "No schema change: every required live concept (request, "
            "response, tool call/result, diagnostic, final output, tokens, "
            "wall time, oracle proof) fits existing generic events."
        ),
    ]


def load_toolperf_ingest(path: Path | None = None) -> dict[str, Any]:
    dest = path or (REPO_ROOT / "results" / "toolperf-ingest.json")
    if not dest.is_file():
        raise FileNotFoundError(
            f"missing {dest}; run ingest-toolperf only if you need JSON, "
            "or point --toolperf at an existing ingest"
        )
    return json.loads(dest.read_text(encoding="utf-8"))


def analyze_toolperf_sanity(ingest: dict[str, Any]) -> dict[str, Any]:
    """Confirm analysis utilities on the frozen 108-run corpus. No re-run."""
    runs = [r for r in (ingest.get("runs") or []) if r.get("model") == QWEN]
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in runs:
        if row.get("success_status") != "reconstructed_from_tail":
            continue
        by_cell[(row["task"], row["arm"])].append(row)

    recovery = []
    for task in RECOVERY_TASKS:
        baseline = by_cell.get((task, "baseline"), [])
        fixes = by_cell.get((task, "fixes"), [])
        recovery.append(_compare_cell(task, baseline, fixes, expect="recovery_win"))

    case_b = by_cell.get((EFFICIENCY_TASK, "baseline"), [])
    case_f = by_cell.get((EFFICIENCY_TASK, "fixes"), [])
    case = _compare_cell(EFFICIENCY_TASK, case_b, case_f, expect="same_success_efficiency_regression")

    ok = all(c.get("passed") for c in recovery) and bool(case.get("passed"))
    return {
        "dataset": ingest.get("dataset"),
        "n_runs_used": sum(len(v) for v in by_cell.values()),
        "model": QWEN,
        "recovery_worth_extra_turns": recovery,
        "err_case_search": case,
        "passed": ok,
        "no_composite_score": True,
        "note": (
            "108-run corpus is an external sanity set. Extra turns after a "
            "parser/truncation recovery are improvement, not waste. "
            "err_case_search is same-success inefficiency."
        ),
    }


def _compare_cell(
    task: str,
    baseline: list[dict[str, Any]],
    fixes: list[dict[str, Any]],
    *,
    expect: str,
) -> dict[str, Any]:
    def _ok(rows: list[dict]) -> tuple[int, int]:
        return sum(1 for r in rows if r.get("success")), len(rows)

    b_ok, b_n = _ok(baseline)
    f_ok, f_n = _ok(fixes)
    b_rate = wilson_interval(b_ok, b_n)
    f_rate = wilson_interval(f_ok, f_n)
    b_eff = _llm_given_success(baseline)
    f_eff = _llm_given_success(fixes)
    b_all = summarize_continuous(_llm(r) for r in baseline)
    f_all = summarize_continuous(_llm(r) for r in fixes)
    b_fail = summarize_continuous(_llm(r) for r in baseline if not r.get("success"))
    f_fail = summarize_continuous(_llm(r) for r in fixes if not r.get("success"))

    if expect == "recovery_win":
        # Baseline fewer turns + fail; fixes more turns + pass.
        passed = (
            (b_rate.get("rate") or 0) < (f_rate.get("rate") or 0)
            and (b_all.get("median") or 0) <= (f_all.get("median") or 0)
        )
        story = "recovery_worth_extra_turns"
    elif expect == "same_success_efficiency_regression":
        passed = (
            b_ok == b_n
            and f_ok == f_n
            and b_n > 0
            and f_n > 0
            and (f_eff.get("median") or 0) > (b_eff.get("median") or 0)
        )
        story = "same_success_efficiency_regression"
    else:
        passed = False
        story = "unknown"

    return {
        "task": task,
        "expect": expect,
        "story": story,
        "passed": passed,
        "baseline": {
            "n": b_n,
            "success": b_rate,
            "llm_all": b_all,
            "llm_given_success": b_eff,
            "llm_given_failure": b_fail,
        },
        "fixes": {
            "n": f_n,
            "success": f_rate,
            "llm_all": f_all,
            "llm_given_success": f_eff,
            "llm_given_failure": f_fail,
        },
        "below_policy_min_n": b_n < MIN_N_FOR_RATE or f_n < MIN_N_FOR_RATE,
    }


def _llm(row: dict[str, Any]) -> float | None:
    metrics = row.get("metrics") or {}
    if isinstance(metrics.get("llm"), (int, float)):
        return float(metrics["llm"])
    if isinstance(row.get("llm"), (int, float)):
        return float(row["llm"])
    return None


def _llm_given_success(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_continuous(_llm(r) for r in rows if r.get("success"))


def render_v04_report(
    *,
    live: dict[str, Any],
    live_result: dict[str, Any] | None,
    toolperf: dict[str, Any],
    fixture_digest: str | None,
    timestamp: str,
) -> str:
    extras = (live_result or {}).get("extras") or {}
    hermes = (live_result or {}).get("hermes_ref") or live.get("hermes_ref") or "n/a"
    harness = (live_result or {}).get("harness_sha") or live.get("harness_sha") or "n/a"
    status = live.get("status")
    lines = [
        "# v0.4 — Live behavioral statistics",
        "",
        f"**Date:** {timestamp}",
        "**Research lane only.** No Hermes core edits. No NousResearch writes.",
        "",
        "Outcome first; efficiency is conditional on outcome. No composite score.",
        "pass@k / pass^k are not reported (N=10 cannot support a meaningful estimate).",
        "",
        "## Experiment configuration",
        "",
        f"- Hermes SHA: `{hermes}`",
        f"- Harness SHA: `{harness}` dirty={(live_result or {}).get('harness_dirty')}",
        f"- Fixture: `zero-toolset-live` digest `{fixture_digest or 'n/a'}`",
        f"- Model: `{live.get('model') or (live_result or {}).get('model') or 'n/a'}`",
        f"- Provider: `{live.get('provider') or (live_result or {}).get('provider') or 'n/a'}`",
        f"- Params: `{json.dumps(live.get('params') or extras.get('model_params') or {}, sort_keys=True)}`",
        f"- N requested: {extras.get('reps') or live.get('reps') or PREFERRED_N} per arm "
        f"(escalate to {ESCALATE_N} if rates sit on a decision boundary)",
        f"- Runtime: {(live_result or {}).get('timestamp') or timestamp}",
        f"- Live status: **{status}**",
        "",
    ]
    if status == "BLOCKED":
        lines.extend(
            [
                "## Live cell — BLOCKED",
                "",
                f"Reason: {live.get('blocked_reason')}",
                "",
                "No synthetic rates. Observatory remains **NOT READY**.",
                "Historical warning comparison (silent SHA vs warning SHA) was skipped.",
                "",
                "The pipeline, noise policy, TraceV1 per-run adapter, and toolperf",
                "sanity check still ship.",
                "",
            ]
        )
    else:
        lines.extend(_render_live_stats(live))
    lines.extend(_render_trace(live.get("trace_integrity") or {}))
    lines.extend(_render_toolperf(toolperf))
    lines.extend(
        [
            "## Readiness",
            "",
            "**Hermes Behavioral Observatory: NOT READY.**",
            "",
            "v0.4 requires real repeated behavior, stable trace scoring, and",
            "statistical reporting. READY also needs at least one adjudicated",
            "production-derived behavioral metric. That is v0.4.1 (the 13 real",
            "ATOF waste episodes), not this pass.",
            "",
            "| Requirement | This pass |",
            "|---|---|",
            f"| Repeated real-model cell | {'RAN' if status == 'RUN' else 'BLOCKED'} |",
            "| Trace scoring stable | yes (per-run + aggregate; schema unchanged) |",
            "| Statistical reporting | yes (Wilson, efficiency given success, failure cost) |",
            "| Adjudicated production-derived metric | no |",
            "",
            "## Next (information gain)",
            "",
            "1. **v0.4.1** — human adjudication of the 13 real ATOF waste episodes.",
            "2. **v0.5** — state/frame-condition contract.",
            "3. **v0.6** — production mining.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt_rate(rate: dict[str, Any] | None) -> str:
    if not rate or rate.get("rate") is None:
        return "n/a"
    ci = rate.get("ci95")
    ci_s = f" 95% Wilson CI [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else ""
    flag = "" if rate.get("reportable", True) else " (N below policy minimum; shown only as a count)"
    return f"{rate['rate']:.3f} (n={rate.get('n')}){ci_s}{flag}"


def _fmt_cont(summary: dict[str, Any] | None, unit: str = "") -> str:
    if not summary or not summary.get("n"):
        return "n/a"
    iqr = summary.get("iqr")
    iqr_s = f", IQR {iqr}" if iqr is not None else ""
    suffix = f" {unit}" if unit else ""
    return f"median {summary.get('median')}{suffix}{iqr_s} (n={summary.get('n')}, min {summary.get('min')}, max {summary.get('max')})"


def _render_live_stats(live: dict[str, Any]) -> list[str]:
    control = live.get("control") or {}
    fault = live.get("fault") or live.get("fault_raw") or {}
    lines = [
        "## Control",
        "",
        f"- Task success: {_fmt_rate((control.get('success')))}",
        f"- Cell valid for fault comparison: **{live.get('cell_valid_for_fault_comparison')}**",
    ]
    if live.get("invalid_reason"):
        lines.append(f"- Invalid reason: {live.get('invalid_reason')}")
    if live.get("recommend_n"):
        lines.append(f"- Rates near a decision boundary; recommend N={live.get('recommend_n')}")
    eff = control.get("efficiency_given_success") or {}
    lines.extend(
        [
            f"- Efficiency given success — turns: {_fmt_cont(eff.get('turns'), 'turns')}",
            f"- Efficiency given success — tool calls: {_fmt_cont(eff.get('tool_calls'))}",
            f"- Efficiency given success — tokens: {_fmt_cont(eff.get('total_tokens'), 'tokens')}",
            f"- Efficiency given success — duration: {_fmt_cont(eff.get('duration_ms'), 'ms')}",
            "",
        ]
    )
    if not live.get("cell_valid_for_fault_comparison"):
        lines.extend(
            [
                "## Fault",
                "",
                "Not interpreted. CONTROL success is not high enough for a",
                "fault comparison. Raw counts remain in `fault_raw` for debug.",
                "",
            ]
        )
        return lines
    modes = fault.get("failure_modes") or {}
    fail = fault.get("failure_cost") or {}
    lines.extend(
        [
            "## Fault",
            "",
            f"- Task success: {_fmt_rate(fault.get('success'))} (expected ≈ 0)",
            f"- Pseudo-tool JSON-like: {_fmt_rate(modes.get('pseudo_json_like'))}",
            f"- Pseudo-tool XML `<function=...>`: {_fmt_rate(modes.get('pseudo_xml_function'))}",
            f"- Pseudo-tool other: {_fmt_rate(modes.get('pseudo_other'))}",
            f"- Hallucinated completion: {_fmt_rate(modes.get('hallucinated_completion'))}",
            f"- Explicit capability failure: {_fmt_rate(modes.get('explicit_capability_failure'))}",
            f"- Remediation requested: {_fmt_rate(modes.get('remediation_requested'))}",
            f"- Diagnostic emitted: {_fmt_rate(modes.get('diagnostic_emitted'))}",
            f"- Failure cost — turns: {_fmt_cont(fail.get('turns'), 'turns')}",
            f"- Failure cost — tokens: {_fmt_cont(fail.get('tokens'), 'tokens')}",
            f"- Failure cost — duration: {_fmt_cont(fail.get('duration_ms'), 'ms')}",
            "",
            (fault.get("note") or ""),
            "",
        ]
    )
    return lines


def _render_trace(integrity: dict[str, Any]) -> list[str]:
    lines = [
        "## Trace integrity",
        "",
        f"- Per-run traces: {integrity.get('n_run_traces', 0)}",
        f"- Valid TraceV1: {integrity.get('n_valid', 0)}",
        f"- Rescored: {integrity.get('n_rescored', 0)}",
        f"- Disagreements: {integrity.get('disagreements', 0)}",
        f"- Aggregate validation errors: {integrity.get('aggregate_errors') or []}",
        "",
        "TraceV1 was **not** modified. Missing live concepts were documented,",
        "not promoted into new event types.",
        "",
    ]
    for gap in integrity.get("schema_gaps") or []:
        lines.append(f"- {gap}")
    missing = integrity.get("missing_telemetry") or []
    if missing:
        lines.append("")
        lines.append("Missing telemetry on individual runs:")
        for item in missing:
            lines.append(f"- {item}")
    lines.append("")
    return lines


def _render_toolperf(toolperf: dict[str, Any]) -> list[str]:
    lines = [
        "## Toolperf analysis sanity",
        "",
        f"Dataset: `{toolperf.get('dataset')}` model `{toolperf.get('model')}`",
        f"Sanity gate: **{'PASS' if toolperf.get('passed') else 'FAIL'}**",
        "",
        toolperf.get("note") or "",
        "",
        "### Recovery worth extra turns (Qwen)",
        "",
        "| task | baseline ok | fixes ok | baseline llm (all) | fixes llm (all) | llm given success (base→fix) | pass |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in toolperf.get("recovery_worth_extra_turns") or []:
        b, f = row["baseline"], row["fixes"]
        lines.append(
            f"| {row['task']} | {_fmt_rate(b['success'])} | {_fmt_rate(f['success'])} | "
            f"{b['llm_all'].get('median')} | {f['llm_all'].get('median')} | "
            f"{b['llm_given_success'].get('median')} → {f['llm_given_success'].get('median')} | "
            f"{'yes' if row.get('passed') else 'no'} |"
        )
    case = toolperf.get("err_case_search") or {}
    b, f = case.get("baseline") or {}, case.get("fixes") or {}
    lines.extend(
        [
            "",
            "### Pure efficiency regression — Qwen `err_case_search`",
            "",
            "Same 100% outcome. More turns is not recovery; it is inefficiency.",
            "",
            f"- baseline success {_fmt_rate(b.get('success'))}, "
            f"llm given success {_fmt_cont(b.get('llm_given_success'), 'turns')}",
            f"- fixes success {_fmt_rate(f.get('success'))}, "
            f"llm given success {_fmt_cont(f.get('llm_given_success'), 'turns')}",
            f"- story: `{case.get('story')}` passed={case.get('passed')}",
            "",
        ]
    )
    return lines
