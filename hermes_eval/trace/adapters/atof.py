"""NeMo Relay ATOF jsonl / summary → TraceV1."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from hermes_eval.redact import redact_obj
from hermes_eval.trace.model import TraceBuilder

ADAPTER = "hermes_eval.trace.adapters.atof"


def emit_atof(
    path: Path | str,
    *,
    fixture: str | None = None,
    hermes_sha: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    src = Path(path)
    text = src.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # jsonl vs a single JSON document with events/atof
    events_in: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    if src.suffix == ".json" and not src.name.endswith(".jsonl"):
        payload = json.loads(text)
        if isinstance(payload, dict):
            summary = payload.get("atof") or {}
            raw = payload.get("events") or []
            events_in = [e for e in raw if isinstance(e, dict)]
            fixture = fixture or payload.get("fixture_id") or payload.get("fixture")
        elif isinstance(payload, list):
            events_in = [e for e in payload if isinstance(e, dict)]
    else:
        for ln in lines:
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if isinstance(ev, dict):
                events_in.append(ev)

    b = TraceBuilder(
        run_id=run_id or f"atof:{src.stem}",
        source="atof",
        adapter=ADAPTER,
        fixture=fixture,
        hermes_sha=hermes_sha,
    )
    b.initial_state = {"path": str(src).replace("\\", "/"), "event_count_in": len(events_in)}
    open_llm: str | None = None
    open_tool: dict[str, str] = {}
    llm = tools = errs = retries = 0
    total_result_bytes = 0
    last_err_tool = None
    for ev in events_in:
        kind, cat, scope = ev.get("kind"), ev.get("category"), ev.get("scope_category")
        name = ev.get("name")
        if kind == "scope" and cat == "llm" and scope == "start":
            open_llm = b.event("model.request", {"name": name, "data_keys": _keys(ev.get("data"))})
        elif kind == "scope" and cat == "llm" and scope == "end":
            b.event(
                "model.response",
                {"name": name, "metadata": _meta(ev)},
                parent_id=open_llm,
            )
            llm += 1
            open_llm = None
        elif kind == "scope" and cat == "tool" and scope == "start":
            data = ev.get("data")
            args = data if isinstance(data, dict) else None
            eid = b.event(
                "tool.call",
                {
                    "name": name,
                    "arguments": redact_obj(args) if args is not None else None,
                    "arguments_hash": _hash_args(args),
                },
            )
            open_tool[str(name)] = eid
            tools += 1
            if last_err_tool == name:
                retries += 1
        elif kind == "scope" and cat == "tool" and scope == "end":
            d = ev.get("data")
            ds = d if isinstance(d, str) else json.dumps(d or "")
            result_bytes = len(ds)
            status = (ev.get("metadata") or {}).get("status") or "ok"
            err = status not in (None, "ok")
            body_looks_like_error = False
            if not err:
                if re.search(r'"error":\s*"(?!null)', ds[:1500]) or re.search(
                    r'"exit_code":\s*[1-9-]', ds[:200]
                ):
                    body_looks_like_error = True
                    err = True
            if err:
                errs += 1
                last_err_tool = name
            else:
                last_err_tool = None
            b.event(
                "tool.result",
                {
                    "name": name,
                    "status": status,
                    "ok": not err,
                    "result_bytes": result_bytes,
                    "body_looks_like_error": body_looks_like_error,
                },
                parent_id=open_tool.get(str(name)),
            )
            total_result_bytes += result_bytes
        elif ev.get("type") in {"tool", "tool_call"}:
            b.event("tool.call", {"name": ev.get("name"), "status": ev.get("status")})
            tools += 1
        elif ev.get("type") in {"llm", "assistant"}:
            b.event("model.response", {"finish_reason": ev.get("finish_reason")})
            llm += 1
        else:
            continue
    if summary:
        tokens = summary.get("tokens") or {}
        b.metrics.update(
            {
                "input_tokens": tokens.get("prompt") or tokens.get("input"),
                "output_tokens": tokens.get("completion") or tokens.get("output"),
                "total_tokens": tokens.get("total"),
            }
        )
        # Event walk is the source of llm/tools/errs/retries/kb. Summary
        # token fields are extra; do not overwrite ATOF event counts.
    kb = total_result_bytes // 1024
    b.metrics.update(
        {
            "llm_turns": llm,
            "turns": llm,
            "tool_calls": tools,
            "tool_errors": errs,
            "retry_after_error": retries,
            "tool_result_bytes": total_result_bytes,
            "errors": errs,
            "retries": retries,
            "kb": kb,
        }
    )
    b.final_state = {
        "llm": llm,
        "tools": tools,
        "errs": errs,
        "retries": retries,
        "kb": kb,
        "tool_result_bytes": total_result_bytes,
    }
    b.event("final.output", dict(b.final_state))
    b.artifacts["paths"].append(str(src).replace("\\", "/"))
    return b.to_dict()


def _hash_args(args: Any) -> str | None:
    if args is None:
        return None
    blob = json.dumps(args, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _keys(data: Any) -> list[str]:
    if isinstance(data, dict):
        return sorted(data)
    return []


def _meta(ev: dict[str, Any]) -> dict[str, Any]:
    meta = ev.get("metadata")
    if isinstance(meta, dict):
        return redact_obj(meta)
    return {}
