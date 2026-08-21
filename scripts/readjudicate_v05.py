#!/usr/bin/env python3
"""Apply the frozen v0.5 human adjudication to completed local cells.

No model calls. The preserved isolated stdout is classified with the current
versioned component scorers, while the two broader terminal buckets use the
explicit human-adjudicated run-id sets below.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.behavior import classify_fault_text
from hermes_eval.trace.adapters.native import emit_native


CELLS = {
    "local-qwen38-zero-toolset-silent-v1": {
        "other": {2, 4, 5, 7, 8, 9},
        "plain": {1, 3, 6},
    },
    "local-qwen35-9b-zero-toolset-silent-v1": {
        "other": {1, 2, 3, 5, 6, 8, 9},
        "plain": {4},
    },
    "local-qwen35-9b-zero-toolset-warning-v1": {
        "other": {2, 4, 6, 8},
        "plain": set(),
    },
}


def rate(rows: list[dict], key: str) -> float:
    return round(sum(bool(row.get(key)) for row in rows) / len(rows), 3)


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    for experiment_id, labels in CELLS.items():
        cell = repo / "results" / "v0.5-cells" / experiment_id
        result_path = cell / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        first_path = result["extras"]["control_runs"][0]["tool_events"][0]["arguments"]["path"]
        run_root = Path(first_path).parents[1]
        rows = result["extras"]["fault_runs"]
        for index, row in enumerate(rows):
            text = (run_root / f"fault-{index}" / "stdout.txt").read_text(
                encoding="utf-8", errors="replace"
            )
            flags = classify_fault_text(
                text,
                task_success=bool(row.get("task_success")),
                actual_tool_calls=int(row.get("actual_tool_calls") or 0),
            )
            row.update(flags)
            row["other_tool_like_text"] = index in labels["other"]
            row["plain_failure_other"] = index in labels["plain"]
            row["transcript_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            row["adjudication"] = "human_v0.5"
            if row["textual_pseudo_tool_call"]:
                terminal = "textual_tool_protocol_failure"
            elif row["hallucinated_completion"]:
                terminal = "hallucinated_completion"
            elif row["explicit_capability_failure"]:
                terminal = "explicit_capability_failure"
            elif row["remediation_requested"]:
                terminal = "remediation_or_user_request"
            elif row["other_tool_like_text"]:
                terminal = "other_tool_like_text"
            else:
                terminal = "plain_failure_other"
                row["plain_failure_other"] = True
            row["terminal_behavior"] = terminal

        extras = result["extras"]
        extras["fault_textual_pseudo_tool_call_rate"] = rate(rows, "textual_pseudo_tool_call")
        extras["fault_pseudo_other_rate"] = rate(rows, "pseudo_other")
        extras["fault_hallucinated_completion_rate"] = rate(rows, "hallucinated_completion")
        extras["fault_explicit_capability_failure_rate"] = rate(rows, "explicit_capability_failure")
        extras["fault_remediation_requested_rate"] = rate(rows, "remediation_requested")
        extras["fault_other_tool_like_text_rate"] = rate(rows, "other_tool_like_text")
        extras["fault_plain_failure_other_rate"] = rate(rows, "plain_failure_other")
        result.setdefault("notes", []).append(
            "v0.5 human readjudication applied; no model calls; transcript content retained only by SHA-256."
        )
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (cell / "trace.json").write_text(
            json.dumps(emit_native(result), indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
