"""External wrap of Hermes request / compression paths. Hashes only.

Does not modify Hermes source. Records SHA-256 prefixes of canonical JSON,
never prompt text, never credentials.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=True).encode("utf-8")


def sha16(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()[:16]


def _message_role_content(msg: Any) -> dict[str, Any]:
    if not isinstance(msg, dict):
        return {"repr": sha16(str(msg))}
    out: dict[str, Any] = {"role": msg.get("role")}
    if "tool_calls" in msg:
        out["tool_calls"] = sha16(msg.get("tool_calls"))
    if "content" in msg:
        out["content"] = sha16(msg.get("content"))
    if "name" in msg:
        out["name"] = msg.get("name")
    extra = sorted(k for k in msg if k not in {"role", "content", "tool_calls", "name"})
    if extra:
        out["extra_keys"] = extra
    return out


def hash_request(api_kwargs: dict[str, Any] | None) -> dict[str, Any]:
    kwargs = api_kwargs or {}
    messages = kwargs.get("messages")
    if not isinstance(messages, list):
        messages = kwargs.get("input") if isinstance(kwargs.get("input"), list) else []
    tools = kwargs.get("tools")
    system = None
    if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        system = messages[0].get("content")
    prefix_k = min(3, len(messages)) if messages else 0
    return {
        "system_prompt_hash": sha16(system) if system is not None else None,
        "tool_schema_hash": sha16(tools) if tools is not None else None,
        "stable_message_prefix_hash": sha16([_message_role_content(m) for m in messages[:prefix_k]])
        if messages
        else None,
        "prefix_k": prefix_k,
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "messages_shape_hash": sha16([_message_role_content(m) for m in messages]) if messages else None,
        "model": kwargs.get("model"),
        "has_tools": bool(tools),
        "tool_count": len(tools) if isinstance(tools, list) else 0,
    }


def wrap_callable(fn: Callable, records: list[dict], kind: str) -> Callable:
    def wrapped(*args, **kwargs):
        payload = None
        if args:
            payload = args[0] if isinstance(args[0], dict) else kwargs
        elif kwargs:
            payload = kwargs
        rec = {
            "kind": kind,
            "request": hash_request(payload if isinstance(payload, dict) else {}),
        }
        try:
            result = fn(*args, **kwargs)
            rec["ok"] = True
            usage = getattr(result, "usage", None)
            if usage is not None:
                rec["input_tokens"] = getattr(usage, "prompt_tokens", None) or getattr(
                    usage, "input_tokens", None
                )
                rec["output_tokens"] = getattr(usage, "completion_tokens", None) or getattr(
                    usage, "output_tokens", None
                )
                rec["cache_read_tokens"] = getattr(usage, "cache_read_tokens", None) or getattr(
                    getattr(usage, "prompt_tokens_details", None),
                    "cached_tokens",
                    None,
                )
                rec["cache_write_tokens"] = getattr(usage, "cache_write_tokens", None)
            return result
        except Exception as exc:
            rec["ok"] = False
            rec["error_type"] = type(exc).__name__
            raise
        finally:
            records.append(rec)

    return wrapped


def prefix_churn(records: list[dict]) -> dict[str, Any]:
    """Flag unexpected prefix changes across LLM calls with no compression."""
    llm = [r for r in records if r.get("kind") in {"interruptible_api_call", "build_api_kwargs", "call_llm"}]
    if len(llm) < 2:
        return {"comparable": False, "reason": "fewer than 2 hashed requests"}
    first = llm[0].get("request") or {}
    unexpected = []
    for idx, rec in enumerate(llm[1:], start=1):
        req = rec.get("request") or {}
        compressed = rec.get("compression_event") or False
        if compressed:
            continue
        for field in ("system_prompt_hash", "tool_schema_hash", "stable_message_prefix_hash"):
            if first.get(field) and req.get(field) and first.get(field) != req.get(field):
                unexpected.append(
                    {
                        "call_index": idx,
                        "field": field,
                        "before": first.get(field),
                        "after": req.get(field),
                    }
                )
    return {
        "comparable": True,
        "calls": len(llm),
        "unexpected_prefix_churn": unexpected,
        "stable": not unexpected,
    }
