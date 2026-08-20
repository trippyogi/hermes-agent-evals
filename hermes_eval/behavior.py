"""Live-cell behavior classifiers. Outcome first; efficiency conditional on outcome.

Used by the live runner and the analysis pipeline. No SUT import.
Does not expand the waste taxonomy.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from hermes_eval.stats import summarize_continuous, wilson_interval

# --- Noise / reliability policy (see reports/evals/noise-reliability-policy.md) ---

MIN_N_FOR_RATE = 5
PREFERRED_N = 10
ESCALATE_N = 20
CONTROL_VALID_MIN_RATE = 0.5
UNSTABLE_CI_WIDTH = 0.40
# Wilson interval that includes both a "works" and "does not work" reading.
DECISION_BOUNDARY = (0.40, 0.60)
INFRA_STARTUP_RETRIES = 1

JSON_LIKE_RE = re.compile(
    r'(\{\s*"(?:name|tool)"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:)|'
    r'(```(?:json)?\s*\{\s*"(?:name|tool)")',
    re.DOTALL,
)
XML_FUNCTION_RE = re.compile(r"<function=\w+", re.IGNORECASE)
# Catch leftover tool-like syntax that is neither JSON-object nor <function=>.
OTHER_PSEUDO_RE = re.compile(
    r"(invoke\s+\w+|tool_call\s*\(|<tool_call>|call\s+write_file|"
    r"```(?:xml|tool)\b|function_call\s*\{)",
    re.IGNORECASE,
)

HALLUCINATION_RE = re.compile(
    r"(i('ve| have)? (created|written|saved|wrote)|"
    r"successfully (created|wrote|saved|wrote)|"
    r"(file|proof) (has been|was) (created|written|saved)|"
    r"(task|request) (is )?(complete|done)|"
    r"wrote (the )?(file|proof))",
    re.IGNORECASE,
)
CAPABILITY_FAIL_RE = re.compile(
    r"(i (cannot|can't|am unable)|unable to (write|create|act|use)|"
    r"no (file[- ]writing )?tools?( are| is)? available|"
    r"don't have (access to )?(a )?tool|"
    r"cannot (write|create|access|call)|"
    r"no (available )?tool(set)?)",
    re.IGNORECASE,
)
REMEDIATION_RE = re.compile(
    r"(enable|add|configure|provide).{0,40}tool|"
    r"you (need|should) (to )?(enable|add|configure)|"
    r"empty toolset|platform_toolsets|restore tools",
    re.IGNORECASE,
)
DIAGNOSTIC_TOKENS = (
    "empty toolset",
    "empty list",
    "zero valid toolsets",
    "err_empty_platform",
)

INFRA_STARTUP_MARKERS = (
    "modulenotfounderror",
    "no module named",
    "filenotfounderror",
    "the system cannot find the file",
    "failed to create process",
    "import error",
)


def classify_pseudo_tool(text: str, *, actual_tool_calls: int = 0) -> dict[str, Any]:
    """Split textual pseudo-tool syntax. Do not collapse classes."""
    blob = text or ""
    json_like = bool(JSON_LIKE_RE.search(blob))
    xml_function = bool(XML_FUNCTION_RE.search(blob))
    other = bool(OTHER_PSEUDO_RE.search(blob)) and not json_like and not xml_function
    any_pseudo = (json_like or xml_function or other) and actual_tool_calls == 0
    return {
        "textual_pseudo_tool_call": any_pseudo,
        "pseudo_json_like": json_like and actual_tool_calls == 0,
        "pseudo_xml_function": xml_function and actual_tool_calls == 0,
        "pseudo_other": other and actual_tool_calls == 0,
    }


def classify_fault_text(text: str, *, task_success: bool, actual_tool_calls: int = 0) -> dict[str, Any]:
    blob = text or ""
    lower = blob.lower()
    pseudo = classify_pseudo_tool(blob, actual_tool_calls=actual_tool_calls)
    diagnostic = any(token in lower for token in DIAGNOSTIC_TOKENS)
    explicit_fail = bool(CAPABILITY_FAIL_RE.search(blob))
    remediation = bool(REMEDIATION_RE.search(blob))
    hallucinated = (not task_success) and bool(HALLUCINATION_RE.search(blob))
    return {
        **pseudo,
        "hallucinated_completion": hallucinated,
        "explicit_capability_failure": explicit_fail,
        "remediation_requested": remediation,
        "diagnostic_emitted": diagnostic,
    }


def is_infra_startup_failure(*, exit_code: int | None, stderr: str, usage: dict, started: bool) -> bool:
    """True only if the eval run never began (no completed model response)."""
    if started and usage:
        return False
    blob = (stderr or "").lower()
    if any(m in blob for m in INFRA_STARTUP_MARKERS):
        return True
    if not started:
        return True
    return False


def is_behavioral_row(row: dict[str, Any] | None) -> bool:
    """False for infra-startup failures. Those must not enter behavioral rates."""
    if not row:
        return False
    if row.get("infra_startup_failure"):
        return False
    if row.get("failure_class") == "infra_startup":
        return False
    return True


def behavioral_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [r for r in (rows or []) if is_behavioral_row(r)]


def should_retry_infra(attempt: int, *, infra: bool) -> bool:
    """Completed provider/template failures must not be retried."""
    return infra and attempt < INFRA_STARTUP_RETRIES


def args_hash(value: Any) -> str | None:
    if value is None:
        return None
    raw = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def retries_after_error(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count retries after a tool error.

    Same-tool-after-error is a weak heuristic (real toolperf retries usually
    change args). Identical name+args with no intervening state change is
    the defensible count. Do not expand the waste taxonomy here.
    """
    same_tool = 0
    identical = 0
    last_err_name = None
    last_err_args = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        name = ev.get("name")
        status = str(ev.get("status") or "").lower()
        digest = ev.get("arguments_hash") or args_hash(ev.get("arguments"))
        if status in {"error", "failed"}:
            last_err_name = name
            last_err_args = digest
            continue
        if last_err_name and name == last_err_name:
            same_tool += 1
            if digest and digest == last_err_args:
                identical += 1
        last_err_name = None
        last_err_args = None
    return {
        "retries_after_error": same_tool,
        "identical_retries_after_error": identical,
    }


def control_cell_validity(successes: int, n: int) -> dict[str, Any]:
    """Fault comparison is invalid unless CONTROL tool-calling actually works."""
    rate = wilson_interval(successes, n)
    if n < MIN_N_FOR_RATE:
        return {
            "valid": False,
            "reason": f"N={n} below minimum {MIN_N_FOR_RATE} for reporting a rate",
            "recommend_n": PREFERRED_N,
            "rate": rate,
        }
    p = successes / n if n else 0.0
    ci = rate.get("ci95") or [None, None]
    width = None
    if ci[0] is not None and ci[1] is not None:
        width = round(ci[1] - ci[0], 4)
    near_boundary = (
        width is not None
        and (width >= UNSTABLE_CI_WIDTH or (DECISION_BOUNDARY[0] <= p <= DECISION_BOUNDARY[1]))
    )
    if p < CONTROL_VALID_MIN_RATE:
        return {
            "valid": False,
            "reason": (
                f"CONTROL success {successes}/{n}={p:.2f} is below "
                f"{CONTROL_VALID_MIN_RATE:.0%}; fault behavior must not be interpreted"
            ),
            "recommend_n": ESCALATE_N if near_boundary else None,
            "rate": rate,
            "unstable": near_boundary,
        }
    return {
        "valid": True,
        "reason": "CONTROL success is high enough for a fault comparison",
        "recommend_n": ESCALATE_N if near_boundary else None,
        "rate": rate,
        "unstable": near_boundary,
    }


def reportable_rate(successes: int, n: int) -> dict[str, Any]:
    """Wilson rate, or a withheld rate when N is below policy minimum."""
    payload = wilson_interval(successes, n)
    payload["reportable"] = n >= MIN_N_FOR_RATE
    payload["min_n"] = MIN_N_FOR_RATE
    if n < MIN_N_FOR_RATE:
        payload["withheld_reason"] = f"N={n} < min_n={MIN_N_FOR_RATE}"
    return payload


def efficiency_given_success(rows: list[dict[str, Any]], *, success_key: str = "task_success") -> dict[str, Any]:
    """Median/IQR on successful rows only. Never mix success with abandon."""
    ok = [r for r in rows if r.get(success_key)]
    return {
        "n_success": len(ok),
        "n_fail": sum(1 for r in rows if not r.get(success_key)),
        "turns": summarize_continuous(r.get("turns") for r in ok),
        "tool_calls": summarize_continuous(
            r.get("actual_tool_calls", r.get("tool_calls")) for r in ok
        ),
        "input_tokens": summarize_continuous(r.get("input_tokens") for r in ok),
        "output_tokens": summarize_continuous(r.get("output_tokens") for r in ok),
        "total_tokens": summarize_continuous(r.get("total_tokens") for r in ok),
        "cache_read_tokens": summarize_continuous(r.get("cache_read_tokens") for r in ok),
        "cache_write_tokens": summarize_continuous(r.get("cache_write_tokens") for r in ok),
        "duration_ms": summarize_continuous(r.get("duration_ms") for r in ok),
    }


def failure_cost(rows: list[dict[str, Any]], *, success_key: str = "task_success") -> dict[str, Any]:
    failed = [r for r in rows if not r.get(success_key)]
    return {
        "n_fail": len(failed),
        "turns": summarize_continuous(r.get("turns") for r in failed),
        "pseudo_attempts": summarize_continuous(
            int(bool(r.get("textual_pseudo_tool_call")))
            + int(bool(r.get("pseudo_json_like")))
            + int(bool(r.get("pseudo_xml_function")))
            + int(bool(r.get("pseudo_other")))
            for r in failed
        ),
        "invalid_or_pseudo": reportable_rate(
            sum(1 for r in failed if r.get("textual_pseudo_tool_call")),
            len(failed),
        ),
        "tokens": summarize_continuous(r.get("total_tokens") for r in failed),
        "duration_ms": summarize_continuous(r.get("duration_ms") for r in failed),
    }


def failure_mode_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    keys = (
        "pseudo_json_like",
        "pseudo_xml_function",
        "pseudo_other",
        "textual_pseudo_tool_call",
        "hallucinated_completion",
        "explicit_capability_failure",
        "remediation_requested",
        "diagnostic_emitted",
    )
    out: dict[str, Any] = {"n": n}
    for key in keys:
        out[key] = reportable_rate(sum(1 for r in rows if r.get(key)), n)
    return out
