"""Live zero-toolset result → TraceV1 (wrapper around native)."""

from __future__ import annotations

from typing import Any

from hermes_eval.trace.adapters.native import emit_native


def emit_live(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("fixture") != "zero-toolset-live":
        result = {**result, "fixture": "zero-toolset-live"}
    return emit_native(result)
