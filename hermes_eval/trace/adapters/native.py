"""Convert hermes-eval result.json extras into TraceV1 observations.

The adapter may know runner shapes. Scorers must not. After emit, extras
can be discarded; scoring uses only the returned trace.
"""

from __future__ import annotations

from typing import Any

from hermes_eval.trace.model import TraceBuilder

ADAPTER = "hermes_eval.trace.adapters.native"


def emit_native(result: dict[str, Any]) -> dict[str, Any]:
    fixture = result.get("fixture") or "unknown"
    dispatch = {
        "zero-toolset": _zero_toolset,
        "delegate-fallback-runtime": _delegate,
        "stale-pin-rescope": _pin,
        "zero-toolset-live": _live,
        "compression-prefix-probe": _prefix,
    }
    fn = dispatch.get(fixture, _generic)
    return fn(result)


def _base(result: dict[str, Any], source: str) -> TraceBuilder:
    prov = result.get("provenance") or {}
    run_id = (
        f"{result.get('fixture') or 'run'}:"
        f"{(result.get('hermes_ref') or 'unknown')[:12]}:"
        f"{(result.get('timestamp') or 'na')}"
    )
    classification = result.get("classification")
    if isinstance(classification, str):
        classification = [classification]
    b = TraceBuilder(
        run_id=run_id,
        source=source,
        adapter=ADAPTER,
        fixture=result.get("fixture"),
        hermes_sha=result.get("hermes_ref") or prov.get("hermes_sha"),
        harness_sha=result.get("harness_sha") or prov.get("harness_sha"),
        harness_dirty=result.get("harness_dirty") if "harness_dirty" in result else prov.get("harness_dirty"),
        model=result.get("model"),
        provider=result.get("provider"),
        classification=classification,
    )
    b.metrics = {
        "turns": result.get("turns"),
        "tool_calls": result.get("tool_calls"),
        "tool_calls_success": result.get("tool_calls_success"),
        "tool_calls_failed": result.get("tool_calls_failed"),
        "invalid_tool_calls": result.get("invalid_tool_calls"),
        "wasted_tool_calls": result.get("wasted_tool_calls"),
        "input_tokens": result.get("input_tokens"),
        "output_tokens": result.get("output_tokens"),
        "total_tokens": result.get("total_tokens"),
        "duration_ms": result.get("duration_ms"),
        "recovered": result.get("recovered"),
        "cache_prefix_stable": result.get("cache_prefix_stable"),
        "not_observable": list(result.get("not_observable") or []),
    }
    for note in result.get("notes") or []:
        b.artifacts["notes"].append(str(note))
    return b


def _arm_events(b: TraceBuilder, arm: dict[str, Any], span_id: str) -> None:
    schemas = arm.get("tool_schemas") or []
    if not isinstance(schemas, list):
        schemas = []
    b.snapshot(
        {
            "arm": span_id,
            "tool_schema_count": arm.get("tool_schema_count", len(schemas)),
            "tool_schemas": schemas,
            "write_file_exposed": arm.get("write_file_exposed"),
            "warning_emitted": arm.get("warning_emitted"),
        },
        span_id=span_id,
    )
    b.event(
        "model.request",
        {
            "arm": span_id,
            "tool_schema_count": arm.get("tool_schema_count", len(schemas)),
        },
        span_id=span_id,
    )
    b.event(
        "model.response",
        {
            "finish_reason": arm.get("finish_reason"),
            "textual_pseudo_tool_call": bool(arm.get("textual_pseudo_tool_call")),
            "transcript_chars": len(str(arm.get("transcript") or "")),
        },
        span_id=span_id,
    )
    for ev in arm.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "tool" or ev.get("name"):
            call_id = b.event(
                "tool.call",
                {
                    "name": ev.get("name"),
                    "status": ev.get("status"),
                },
                span_id=span_id,
            )
            b.event(
                "tool.result",
                {
                    "name": ev.get("name"),
                    "status": ev.get("status"),
                    "ok": ev.get("status") == "ok",
                },
                span_id=span_id,
                parent_id=call_id,
            )
    if arm.get("warning_emitted"):
        b.diagnostic(
            "empty-toolset",
            "named empty-list / zero-toolset diagnostic",
            span_id=span_id,
            extra={"warnings": list(arm.get("warnings") or [])},
        )
    elif arm.get("arm") == "fault" or span_id == "fault":
        if (arm.get("tool_schema_count") or 0) == 0:
            b.diagnostic(
                "empty-toolset-silent",
                "zero tools with no named empty-list diagnostic",
                span_id=span_id,
                extra={"warnings": list(arm.get("warnings") or [])},
            )
    b.event(
        "final.output",
        {
            "proof_exists": bool(arm.get("proof_exists")),
            "tool_calls": arm.get("tool_calls") or 0,
            "textual_pseudo_tool_call": bool(arm.get("textual_pseudo_tool_call")),
        },
        span_id=span_id,
    )


def _zero_toolset(result: dict[str, Any]) -> dict[str, Any]:
    extras = result.get("extras") or {}
    control = extras.get("control") or {}
    fault = extras.get("fault") or {}
    b = _base(result, "hermes_eval_native")
    b.initial_state = {
        "control": {"platform_toolsets": {"cli": ["hermes-cli"]}},
        "fault": {
            "platform_toolsets": {
                "cli": [],
                "telegram": ["hermes-telegram"],
                "discord": ["hermes-discord"],
            }
        },
    }
    _arm_events(b, control, "control")
    _arm_events(b, fault, "fault")
    b.final_state = {
        "control": {
            "proof_exists": bool(control.get("proof_exists")),
            "tool_schema_count": control.get("tool_schema_count"),
            "tool_calls": control.get("tool_calls") or 0,
        },
        "fault": {
            "proof_exists": bool(fault.get("proof_exists")),
            "tool_schema_count": fault.get("tool_schema_count"),
            "tool_calls": fault.get("tool_calls") or 0,
            "textual_pseudo_tool_call": bool(fault.get("textual_pseudo_tool_call")),
            "warning_emitted": bool(fault.get("warning_emitted")),
        },
    }
    return b.to_dict()


def _delegate(result: dict[str, Any]) -> dict[str, Any]:
    extras = result.get("extras") or {}
    b = _base(result, "hermes_eval_native")
    b.initial_state = {
        "parent_primary": {
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "api_mode": "codex_responses",
        },
        "fault_injected": True,
        "fault_class": "split-brain-parent-runtime-after-fallback",
    }
    parent = extras.get("parent_after_fallback") or {}
    child = extras.get("child_runtime")
    expected = extras.get("expected_child") or {}
    b.snapshot(
        {
            "role": "parent_after_fallback",
            "provider": parent.get("provider"),
            "model": parent.get("model"),
            "base_url": parent.get("base_url"),
            "api_mode": parent.get("api_mode"),
            "credential_class": parent.get("credential_class"),
            "fallback_activated": bool(extras.get("fallback_activated")),
        },
        span_id="parent",
    )
    if extras.get("fallback_activated"):
        b.diagnostic(
            "fault-injected-split-brain",
            "anthropic pair + stale Codex surface after fallback",
            span_id="parent",
        )
    start = b.event(
        "delegate.start",
        {"goal": "write proof that the child runtime is coherent", "task_index": 0},
        span_id="child",
        parent_id=None,
    )
    end_payload = {
        "built": bool(extras.get("child_built")),
        "fail_closed": bool(extras.get("fail_closed")),
        "runtime_coherent": bool(extras.get("runtime_coherent")),
        "auth_failures": extras.get("auth_failures"),
        "child": child,
    }
    b.event("delegate.end", end_payload, span_id="child", parent_id=start)
    if child:
        b.snapshot({"role": "child_runtime", **child}, span_id="child")
    b.event(
        "final.output",
        {
            "child_built": bool(extras.get("child_built")),
            "fail_closed": bool(extras.get("fail_closed")),
            "auth_failures": extras.get("auth_failures") or 0,
        },
        span_id="child",
    )
    b.final_state = {
        "fallback_activated": bool(extras.get("fallback_activated")),
        "child_runtime": child,
        "child_built": bool(extras.get("child_built")),
        "fail_closed": bool(extras.get("fail_closed")),
        "auth_failures": extras.get("auth_failures") or 0,
        "expected_fallback_provider": expected.get("provider") or "anthropic",
        "expected_fallback_api_mode": expected.get("api_mode") or "anthropic_messages",
        "expected_fallback_credential_class": expected.get("credential_class") or "anthropic-key",
        "expected_fallback_base_url": expected.get("base_url") or "https://api.anthropic.com",
        "expected_fallback_model": expected.get("model") or "claude-sonnet-5",
    }
    return b.to_dict()


def _pin(result: dict[str, Any]) -> dict[str, Any]:
    extras = result.get("extras") or {}
    b = _base(result, "hermes_eval_native")
    b.initial_state = {
        "gateway": {"mode": "remote", "baseUrl": "https://gw.example:8443"},
        "session": "S",
        "pin_includes_profile": extras.get("pin_includes_profile"),
    }
    b.snapshot(
        {
            "pin_includes_profile": extras.get("pin_includes_profile"),
            "policy": (result.get("notes") or [None])[0],
        },
        span_id="store",
    )
    for ev in extras.get("events") or []:
        if not isinstance(ev, dict):
            continue
        b.event(
            "state.delta",
            {
                "op": ev.get("op"),
                "id": ev.get("id"),
                "profile": ev.get("profile"),
                "local": ev.get("local"),
                "user_action": ev.get("op") in {"pin", "unpin"},
            },
            span_id="store",
        )
    for patch in extras.get("patches") or []:
        if not isinstance(patch, dict):
            continue
        b.event(
            "state.delta",
            {
                "op": "PATCH",
                "session": patch.get("id"),
                "pinned": patch.get("pinned"),
                "user_action": bool(patch.get("user_action")),
                "profile": patch.get("profile"),
            },
            span_id="store",
        )
    local = list(extras.get("local_final") or [])
    backend = dict(extras.get("backend_final") or {})
    b.snapshot(
        {
            "local": local,
            "backend": backend,
            "session_S_pinned": "S" in local or backend.get("S") is True,
        },
        span_id="store",
    )
    b.event(
        "final.output",
        {
            "final_unpinned": bool(extras.get("final_unpinned")),
            "unsolicited_pin_patches": extras.get("unsolicited_pin_patches") or 0,
        },
        span_id="store",
    )
    b.final_state = {
        "local": local,
        "backend": backend,
        "session.S.pinned": "S" in local or backend.get("S") is True,
        "unsolicited_pin_patches": extras.get("unsolicited_pin_patches"),
        "final_unpinned": extras.get("final_unpinned"),
    }
    return b.to_dict()


def _live(result: dict[str, Any]) -> dict[str, Any]:
    extras = result.get("extras") or {}
    b = _base(result, "live_zero_toolset")
    b.provenance["source"] = "live_zero_toolset"
    status = result.get("status") or "UNKNOWN"
    b.initial_state = {"status": status, "reps": extras.get("reps")}
    if status == "BLOCKED":
        b.diagnostic(
            "live-blocked",
            extras.get("blocked_reason") or "missing HERMES_EVAL_* credentials",
        )
        b.final_state = {
            "status": "BLOCKED",
            "synthetic_substitution": False,
            "rates": None,
        }
        return b.to_dict()
    for i, row in enumerate(extras.get("control_runs") or []):
        span = f"control:{i}"
        _live_row(b, row, span, "control")
    for i, row in enumerate(extras.get("fault_runs") or []):
        span = f"fault:{i}"
        _live_row(b, row, span, "fault")
    b.final_state = {
        "status": "RUN",
        "control_task_success_rate": extras.get("control_task_success_rate"),
        "fault_task_success_rate": extras.get("fault_task_success_rate"),
        "fault_textual_pseudo_tool_call_rate": extras.get("fault_textual_pseudo_tool_call_rate"),
        "fault_diagnostic_rate": extras.get("fault_diagnostic_rate"),
        "fault_mean_actual_tool_calls": extras.get("fault_mean_actual_tool_calls"),
        "synthetic_substitution": False,
    }
    b.metrics.update(
        {
            "control_task_success_rate": extras.get("control_task_success_rate"),
            "fault_task_success_rate": extras.get("fault_task_success_rate"),
            "fault_textual_pseudo_tool_call_rate": extras.get("fault_textual_pseudo_tool_call_rate"),
            "fault_diagnostic_rate": extras.get("fault_diagnostic_rate"),
        }
    )
    return b.to_dict()


def _live_row(b: TraceBuilder, row: dict[str, Any], span: str, arm: str) -> None:
    b.snapshot(
        {
            "arm": arm,
            "task_success": row.get("task_success"),
            "proof_exists": row.get("proof_exists"),
            "actual_tool_calls": row.get("actual_tool_calls"),
        },
        span_id=span,
    )
    b.event(
        "model.response",
        {
            "textual_pseudo_tool_call": bool(row.get("textual_pseudo_tool_call")),
            "turns": row.get("turns"),
        },
        span_id=span,
    )
    if row.get("diagnostic_emitted"):
        b.diagnostic("empty-toolset", "live diagnostic", span_id=span)
    b.event(
        "final.output",
        {
            "proof_exists": bool(row.get("proof_exists")),
            "task_success": bool(row.get("task_success")),
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "duration_ms": row.get("duration_ms"),
        },
        span_id=span,
    )


def _prefix(result: dict[str, Any]) -> dict[str, Any]:
    extras = result.get("extras") or {}
    b = _base(result, "prefix_probe")
    b.provenance["source"] = "prefix_probe"
    b.initial_state = {"session_model": extras.get("session_model")}
    t1_sys = t1_tools = None
    for row in extras.get("longitudinal_turns") or []:
        turn = row.get("turn")
        span = str(turn or "turn")
        compression = bool(row.get("compression_event"))
        if compression:
            b.event("compression.start", {"turn": turn}, span_id=span)
        b.event(
            "model.request",
            {
                "turn": turn,
                "system_hash": row.get("system_hash"),
                "tools_hash": row.get("tools_hash"),
                "message_count": row.get("message_count"),
                "shared_prefix_count": row.get("shared_prefix_count"),
                "prefix_retention_ratio": row.get("prefix_retention_ratio"),
                "first_divergence": row.get("first_divergence"),
                "compression_event": compression,
            },
            span_id=span,
        )
        if compression:
            b.event(
                "compression.end",
                {
                    "turn": turn,
                    "system_hash": row.get("system_hash"),
                    "prefix_retention_ratio": row.get("prefix_retention_ratio"),
                    "first_divergence": row.get("first_divergence"),
                },
                span_id=span,
            )
        if turn == "T1":
            t1_sys, t1_tools = row.get("system_hash"), row.get("tools_hash")
    for row in extras.get("prefix_policy") or []:
        b.event(
            "model.request",
            {"policy_event": True, **row},
            span_id=str(row.get("event") or "policy"),
        )
    b.final_state = {
        "longitudinal_turns": extras.get("longitudinal_turns") or [],
        "prefix_policy": extras.get("prefix_policy") or [],
        "t1_system_hash": t1_sys,
        "t1_tools_hash": t1_tools,
        "cache_eligible_prefix_stable": result.get("cache_prefix_stable"),
        "provider_cache_hit": "not_observable",
    }
    return b.to_dict()


def _generic(result: dict[str, Any]) -> dict[str, Any]:
    b = _base(result, "hermes_eval_native")
    extras = result.get("extras") or {}
    b.initial_state = {"fixture": result.get("fixture")}
    if extras:
        b.snapshot({"extras_keys": sorted(extras)}, span_id="run")
    b.event("final.output", {"success_field_ignored_by_scorer": True}, span_id="run")
    b.final_state = {"notes": list(result.get("notes") or [])}
    return b.to_dict()
