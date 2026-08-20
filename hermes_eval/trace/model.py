"""TraceV1 builder and accessors. No secrets; redaction metadata on every event."""

from __future__ import annotations

from typing import Any, Iterable

TRACE_VERSION = "trace-v1"
EVENT_TYPES = (
    "model.request",
    "model.response",
    "tool.call",
    "tool.result",
    "state.snapshot",
    "state.delta",
    "delegate.start",
    "delegate.end",
    "compression.start",
    "compression.end",
    "diagnostic",
    "final.output",
)
DEFAULT_REDACTION = {
    "secrets": "fingerprint_only",
    "transcript": "omitted_or_hashed",
}

REQUIRED_TOP = (
    "trace_version",
    "run_id",
    "provenance",
    "initial_state",
    "events",
    "final_state",
    "artifacts",
    "metrics",
)


def validate_trace(trace: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(trace, dict):
        return ["trace is not an object"]
    if trace.get("trace_version") != TRACE_VERSION:
        errors.append(f"trace_version {trace.get('trace_version')!r} != {TRACE_VERSION}")
    for key in REQUIRED_TOP:
        if key not in trace:
            errors.append(f"missing {key}")
    events = trace.get("events")
    if not isinstance(events, list):
        errors.append("events must be a list")
        return errors
    seen: set[str] = set()
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            errors.append(f"events[{i}] not an object")
            continue
        eid = ev.get("id")
        if not eid:
            errors.append(f"events[{i}] missing id")
        elif eid in seen:
            errors.append(f"duplicate event id {eid}")
        else:
            seen.add(str(eid))
        if ev.get("seq") != i:
            errors.append(f"events[{i}] seq {ev.get('seq')!r} != {i}")
        if ev.get("type") not in EVENT_TYPES:
            errors.append(f"events[{i}] type {ev.get('type')!r} not in TraceV1")
    return errors


def events_of(
    trace: dict[str, Any],
    *,
    type: str | None = None,
    types: Iterable[str] | None = None,
    span_id: str | None = None,
) -> list[dict[str, Any]]:
    wanted = {type} if type else (set(types) if types else None)
    out = []
    for ev in trace.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if wanted is not None and ev.get("type") not in wanted:
            continue
        if span_id is not None and ev.get("span_id") != span_id:
            continue
        out.append(ev)
    return out


def spans(trace: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in trace.get("events") or []:
        if not isinstance(ev, dict):
            continue
        grouped.setdefault(str(ev.get("span_id") or "run"), []).append(ev)
    return grouped


class TraceBuilder:
    def __init__(
        self,
        *,
        run_id: str,
        source: str,
        adapter: str,
        fixture: str | None = None,
        hermes_sha: str | None = None,
        harness_sha: str | None = None,
        harness_dirty: bool | None = None,
        model: str | None = None,
        provider: str | None = None,
        classification: list[str] | None = None,
        initial_state: dict[str, Any] | None = None,
    ):
        self.run_id = run_id
        self.provenance = {
            "source": source,
            "adapter": adapter,
            "fixture": fixture,
            "hermes_sha": hermes_sha,
            "harness_sha": harness_sha,
            "harness_dirty": harness_dirty,
            "model": model,
            "provider": provider,
            "classification": classification,
            "redaction": dict(DEFAULT_REDACTION),
        }
        self.initial_state = initial_state or {}
        self.final_state: dict[str, Any] = {}
        self.artifacts: dict[str, Any] = {"paths": [], "notes": []}
        self.metrics: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []

    def event(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        *,
        span_id: str | None = None,
        parent_id: str | None = None,
        ts: str | None = None,
        redaction: dict[str, Any] | None = None,
    ) -> str:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown TraceV1 event type {type!r}")
        seq = len(self._events)
        eid = f"{self.run_id}:{seq:04d}"
        self._events.append(
            {
                "id": eid,
                "seq": seq,
                "type": type,
                "span_id": span_id,
                "parent_id": parent_id,
                "ts": ts,
                "redaction": redaction or dict(DEFAULT_REDACTION),
                "payload": payload or {},
            }
        )
        return eid

    def snapshot(self, state: dict[str, Any], *, span_id: str | None = None) -> str:
        return self.event("state.snapshot", dict(state), span_id=span_id)

    def diagnostic(
        self,
        code: str,
        message: str,
        *,
        span_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        payload = {"code": code, "message": message}
        if extra:
            payload.update(extra)
        return self.event("diagnostic", payload, span_id=span_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_version": TRACE_VERSION,
            "run_id": self.run_id,
            "provenance": dict(self.provenance),
            "initial_state": dict(self.initial_state),
            "events": list(self._events),
            "final_state": dict(self.final_state),
            "artifacts": dict(self.artifacts),
            "metrics": dict(self.metrics),
        }
