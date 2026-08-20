"""Prefix-probe result → TraceV1 (wrapper around native)."""

from __future__ import annotations

from typing import Any

from hermes_eval.trace.adapters.native import emit_native


def emit_prefix(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("fixture") != "compression-prefix-probe":
        result = {**result, "fixture": "compression-prefix-probe"}
    return emit_native(result)
