"""Score TraceV1 only. Fixture YAML is the contract. Runner extras are illegal input."""

from __future__ import annotations

from typing import Any

from hermes_eval.fixtureload import load_fixture
from hermes_eval.trace.adapters.atof import emit_atof
from hermes_eval.trace.adapters.native import emit_native
from hermes_eval.trace.model import events_of, validate_trace

SCORERS = {
    "zero-toolset": "score_zero_toolset",
    "delegate-fallback-runtime": "score_delegate",
    "stale-pin-rescope": "score_pin",
    "zero-toolset-live": "score_live",
    "compression-prefix-probe": "score_prefix",
}


def emit_trace(result: dict[str, Any]) -> dict[str, Any]:
    return emit_native(result)


def score_trace(trace: dict[str, Any]) -> dict[str, Any]:
    errors = validate_trace(trace)
    fixture = (trace.get("provenance") or {}).get("fixture")
    if errors:
        return {
            "fixture": fixture,
            "success": False,
            "notes": errors,
            "scored_from": "trace-v1",
            "metrics": {},
        }
    dispatch = {
        "zero-toolset": score_zero_toolset,
        "delegate-fallback-runtime": score_delegate,
        "stale-pin-rescope": score_pin,
        "zero-toolset-live": score_live,
        "compression-prefix-probe": score_prefix,
    }
    fn = dispatch.get(fixture)
    if fn is None:
        return {
            "fixture": fixture,
            "success": False,
            "notes": [f"no TraceV1 scorer for {fixture!r}"],
            "scored_from": "trace-v1",
            "metrics": {},
        }
    payload = fn(trace)
    payload["fixture"] = fixture
    payload["scored_from"] = "trace-v1"
    payload.setdefault("notes", [])
    payload.setdefault("metrics", {})
    return payload


def result_from_trace(trace: dict[str, Any], *, hermes_ref: str | None = None) -> dict[str, Any]:
    """Build a compare-compatible result dict from a trace score. No extras."""
    scored = score_trace(trace)
    prov = trace.get("provenance") or {}
    metrics = trace.get("metrics") or {}
    return {
        "fixture": scored.get("fixture") or prov.get("fixture"),
        "hermes_ref": hermes_ref or prov.get("hermes_sha"),
        "success": bool(scored.get("success")),
        "recovered": scored.get("recovered", scored.get("success")),
        "turns": metrics.get("turns"),
        "tool_calls": metrics.get("tool_calls"),
        "invalid_tool_calls": metrics.get("invalid_tool_calls"),
        "wasted_tool_calls": metrics.get("wasted_tool_calls"),
        "duration_ms": metrics.get("duration_ms"),
        "notes": list(scored.get("notes") or []),
        "scored_from": "trace-v1",
        "trace_score": scored,
        "extras": {},
    }


def score_zero_toolset(trace: dict[str, Any]) -> dict[str, Any]:
    control_ok, c_notes = _zero_control(trace)
    fault_closed, f_notes = _zero_fault_closed(trace)
    diagnostic = _has_diagnostic(trace, "empty-toolset", span_id="fault")
    success = control_ok and fault_closed and diagnostic
    notes = c_notes + f_notes
    if diagnostic:
        notes.append("fault arm surfaced a named empty-list / zero-toolset diagnostic")
    elif fault_closed:
        notes.append("fault arm silent: zero tools, no named empty-list diagnostic")
    return {
        "success": success,
        "recovered": diagnostic if fault_closed else False,
        "notes": notes,
        "metrics": {
            "control_ok": control_ok,
            "fault_fail_closed": fault_closed,
            "diagnostic_emitted": diagnostic,
        },
    }


def _span_snapshot(trace: dict[str, Any], span_id: str) -> dict[str, Any]:
    snaps = events_of(trace, type="state.snapshot", span_id=span_id)
    if not snaps:
        return {}
    payload = snaps[0].get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _span_final(trace: dict[str, Any], span_id: str) -> dict[str, Any]:
    outs = events_of(trace, type="final.output", span_id=span_id)
    if not outs:
        return {}
    payload = outs[-1].get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _zero_control(trace: dict[str, Any]) -> tuple[bool, list[str]]:
    snap = _span_snapshot(trace, "control")
    final = _span_final(trace, "control")
    schemas = snap.get("tool_schema_count")
    if schemas is None:
        schemas = len(snap.get("tool_schemas") or [])
    proof = bool(final.get("proof_exists"))
    calls = events_of(trace, type="tool.call", span_id="control")
    ok = bool(proof and isinstance(schemas, int) and schemas > 0 and calls)
    notes = []
    if not ok:
        notes.append("control arm failed: expected write_file proof under a normal toolset")
    return ok, notes


def _zero_fault_closed(trace: dict[str, Any]) -> tuple[bool, list[str]]:
    snap = _span_snapshot(trace, "fault")
    final = _span_final(trace, "fault")
    schemas = snap.get("tool_schema_count")
    if schemas is None:
        schemas = len(snap.get("tool_schemas") or [])
    proof = bool(final.get("proof_exists"))
    calls = events_of(trace, type="tool.call", span_id="fault")
    resp = events_of(trace, type="model.response", span_id="fault")
    textual = bool(final.get("textual_pseudo_tool_call"))
    if not textual:
        textual = any((e.get("payload") or {}).get("textual_pseudo_tool_call") for e in resp)
    closed = schemas == 0 and not calls and not proof and textual
    notes = []
    if not closed:
        notes.append("fault arm did not stay fail-closed / text-as-tool")
    return closed, notes


def _has_diagnostic(trace: dict[str, Any], code: str, span_id: str | None = None) -> bool:
    for ev in events_of(trace, type="diagnostic", span_id=span_id):
        if (ev.get("payload") or {}).get("code") == code:
            return True
    return False


def score_delegate(trace: dict[str, Any]) -> dict[str, Any]:
    spec = load_fixture("delegate-fallback-runtime")
    expected = (spec.get("setup") or {}).get("parent_fallback") or {}
    snaps = events_of(trace, type="state.snapshot")
    parent = {}
    child = {}
    for ev in snaps:
        payload = ev.get("payload") or {}
        if payload.get("role") == "parent_after_fallback":
            parent = payload
        if payload.get("role") == "child_runtime":
            child = payload
    ends = events_of(trace, type="delegate.end")
    end = (ends[-1].get("payload") or {}) if ends else {}
    if not child and isinstance(end.get("child"), dict):
        child = end["child"]
    fallback_ok = bool(parent.get("fallback_activated"))
    if not fallback_ok:
        # snapshot may store it; also diagnostic
        fallback_ok = _has_diagnostic(trace, "fault-injected-split-brain")
    built = bool(end.get("built") or child)
    fail_closed = bool(end.get("fail_closed"))
    coherent = _identity_match(child, expected)
    auth_fail = _auth_mismatch(child, expected) if child else True
    if fail_closed and not child:
        auth_fail = True
    success = bool(fallback_ok and coherent and not auth_fail)
    notes = []
    if not fallback_ok:
        notes.append("parent did not activate fallback")
    if built and not coherent:
        notes.append("child runtime does not match fallback F")
    if fail_closed and not coherent:
        notes.append("fail-closed instead of inheriting fallback F")
    if coherent:
        notes.append("child inherited complete fallback runtime F")
    return {
        "success": success,
        "recovered": coherent,
        "notes": notes,
        "metrics": {
            "fallback_activated": fallback_ok,
            "runtime_coherent": coherent,
            "auth_failures": 1 if auth_fail else 0,
            "child_built": built,
        },
    }


def _identity_match(child: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not child or not expected:
        return False
    fields = ("provider", "model", "base_url", "api_mode", "credential_class")
    for key in fields:
        got = child.get(key)
        want = expected.get(key)
        if key == "base_url" and got and want:
            if str(got).rstrip("/") != str(want).rstrip("/"):
                return False
            continue
        if got != want:
            return False
    return True


def _auth_mismatch(child: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not child.get("base_url") or not expected.get("base_url"):
        return True
    host_ok = str(child["base_url"]).rstrip("/") == str(expected["base_url"]).rstrip("/")
    cred_ok = child.get("credential_class") == expected.get("credential_class")
    mode_ok = child.get("api_mode") == expected.get("api_mode")
    return not (host_ok and cred_ok and mode_ok)


def score_pin(trace: dict[str, Any]) -> dict[str, Any]:
    patches = []
    for ev in events_of(trace, type="state.delta"):
        payload = ev.get("payload") or {}
        if payload.get("op") == "PATCH":
            patches.append(payload)
    unpin_idx = next(
        (
            i
            for i, p in enumerate(patches)
            if p.get("session") == "S" and p.get("pinned") is False and p.get("user_action")
        ),
        None,
    )
    unsolicited = 0
    if unpin_idx is not None:
        unsolicited = sum(
            1
            for p in patches[unpin_idx + 1 :]
            if p.get("pinned") is True and not p.get("user_action")
        )
    snaps = events_of(trace, type="state.snapshot", span_id="store")
    last = (snaps[-1].get("payload") or {}) if snaps else {}
    local = list(last.get("local") or [])
    backend = dict(last.get("backend") or {})
    s_pinned = last.get("session_S_pinned")
    if s_pinned is None:
        s_pinned = "S" in local or backend.get("S") is True
    final_unpinned = s_pinned is False
    success = final_unpinned and unsolicited == 0
    notes = []
    if success:
        notes.append("S stayed unpinned across A→B→A; no unsolicited PATCH pinned=true")
    else:
        notes.append(
            f"stale republish: unsolicited_pin_patches={unsolicited} final_unpinned={final_unpinned}"
        )
    return {
        "success": success,
        "recovered": success,
        "notes": notes,
        "metrics": {
            "unsolicited_pin_patches": unsolicited,
            "final_unpinned": final_unpinned,
        },
    }


def score_live(trace: dict[str, Any]) -> dict[str, Any]:
    status = (trace.get("final_state") or {}).get("status")
    if status is None and _has_diagnostic(trace, "live-blocked"):
        status = "BLOCKED"
    if status == "BLOCKED":
        return {
            "success": False,
            "status": "BLOCKED",
            "notes": ["Live matrix BLOCKED. No synthetic numbers substituted."],
            "metrics": {"synthetic_substitution": False},
        }
    final = trace.get("final_state") or {}
    return {
        "success": True,
        "status": "RUN",
        "notes": [
            "Fault-arm task success is expected ~0. Known-good makes zero tools loud.",
        ],
        "metrics": {
            "control_task_success_rate": final.get("control_task_success_rate"),
            "fault_task_success_rate": final.get("fault_task_success_rate"),
            "fault_textual_pseudo_tool_call_rate": final.get("fault_textual_pseudo_tool_call_rate"),
            "fault_diagnostic_rate": final.get("fault_diagnostic_rate"),
            "synthetic_substitution": False,
        },
    }


def score_prefix(trace: dict[str, Any]) -> dict[str, Any]:
    reqs = [
        e
        for e in events_of(trace, type="model.request")
        if not (e.get("payload") or {}).get("policy_event")
    ]
    turns = [(e.get("payload") or {}).get("turn") for e in reqs]
    measurable = any((e.get("payload") or {}).get("system_hash") for e in reqs)
    success = measurable and {"T1", "T2", "T3", "T4", "T5"}.issubset(set(turns))
    return {
        "success": success,
        "notes": [],
        "metrics": {"turns_observed": turns, "measurable": measurable},
    }


def score_atof_file(path: str, **kwargs: Any) -> dict[str, Any]:
    trace = emit_atof(path, **kwargs)
    errors = validate_trace(trace)
    return {
        "success": not errors,
        "trace": trace,
        "errors": errors,
        "metrics": trace.get("metrics") or {},
        "scored_from": "trace-v1",
    }
