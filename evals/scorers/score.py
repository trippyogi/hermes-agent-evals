"""Score a run result. Null/not_observable stay explicit. No magic score."""

from __future__ import annotations

import json
from typing import Any

REGRESSION_RULES = (
    ("task_success", "PASS", "FAIL"),
    ("recovery", "PASS", "FAIL"),
)


def _flag(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if baseline.get("success") is True and candidate.get("success") is False:
        flags.append("task_success PASS→FAIL")
    b_rec = baseline.get("recovered")
    c_rec = candidate.get("recovered")
    if b_rec is True and c_rec is False:
        flags.append("recovery PASS→FAIL")
    b_inv = baseline.get("invalid_tool_calls")
    c_inv = candidate.get("invalid_tool_calls")
    if isinstance(b_inv, int) and isinstance(c_inv, int) and b_inv == 0 and c_inv > 0:
        flags.append("invalid_tool_calls 0→>0")
    b_waste = baseline.get("wasted_tool_calls")
    c_waste = candidate.get("wasted_tool_calls")
    if isinstance(b_waste, int) and isinstance(c_waste, int) and c_waste > b_waste:
        flags.append("wasted_tool_calls increased")
    b_turns = baseline.get("turns")
    c_turns = candidate.get("turns")
    if (
        isinstance(b_turns, (int, float))
        and isinstance(c_turns, (int, float))
        and c_turns > b_turns
        and candidate.get("success") != True
    ):
        flags.append("turns increased with no quality gain")
    if baseline.get("cache_prefix_stable") is True and candidate.get("cache_prefix_stable") is False:
        flags.append("cache/prefix invariant broke")
    return flags


def compare_pair(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    distinguished = baseline.get("success") != candidate.get("success")
    extras_b = baseline.get("extras") or {}
    extras_c = candidate.get("extras") or {}
    return {
        "fixture": baseline.get("fixture") or candidate.get("fixture"),
        "baseline_ref": baseline.get("hermes_ref"),
        "candidate_ref": candidate.get("hermes_ref"),
        "baseline_success": baseline.get("success"),
        "candidate_success": candidate.get("success"),
        "distinguished": distinguished,
        "direction": (
            "candidate_fixed"
            if (baseline.get("success") is False and candidate.get("success") is True)
            else "candidate_regressed"
            if (baseline.get("success") is True and candidate.get("success") is False)
            else "no_change"
        ),
        "flags": _flag(baseline, candidate),
        "metrics": {
            "turns": [baseline.get("turns"), candidate.get("turns")],
            "tool_calls": [baseline.get("tool_calls"), candidate.get("tool_calls")],
            "invalid_tool_calls": [
                baseline.get("invalid_tool_calls"),
                candidate.get("invalid_tool_calls"),
            ],
            "wasted_tool_calls": [
                baseline.get("wasted_tool_calls"),
                candidate.get("wasted_tool_calls"),
            ],
            "recovered": [baseline.get("recovered"), candidate.get("recovered")],
            "duration_ms": [baseline.get("duration_ms"), candidate.get("duration_ms")],
        },
        "extras_delta": {
            key: [extras_b.get(key), extras_c.get(key)]
            for key in sorted(set(extras_b) | set(extras_c))
            if extras_b.get(key) != extras_c.get(key)
            and key
            not in {
                "hermes_home",
                "control",
                "fault",
                "events",
                "patches",
                "transcript",
            }
        },
    }


def load_json(path: str) -> dict[str, Any]:
    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8"))
