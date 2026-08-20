"""Append-only current-canary index. Bulky traces stay in results/ as artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_eval.freeze import freeze_payload
from hermes_eval.gitutil import REPO_ROOT, harness_git_state

INDEX_PATH = REPO_ROOT / "evals" / "provenance" / "canary-index.jsonl"


def fixture_digest_map() -> dict[str, str]:
    payload = freeze_payload()
    return {row["path"]: row["sha256"] for row in payload.get("files") or [] if row.get("sha256")}


def index_row(report: dict[str, Any]) -> dict[str, Any]:
    git_state = harness_git_state()
    digests = fixture_digest_map()
    return {
        "date": (report.get("timestamp") or datetime.now(timezone.utc).isoformat())[:10],
        "timestamp": report.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "hermes_sha": report.get("current_sha"),
        "harness_sha": report.get("harness_sha") or git_state["harness_sha"],
        "harness_dirty": report.get("harness_dirty") if "harness_dirty" in report else git_state["harness_dirty"],
        "fixture_digest": digests,
        "status": [row.get("status") for row in report.get("fixtures") or []],
        "fixtures": [
            {
                "fixture": row.get("fixture"),
                "status": row.get("status"),
                "known_good_is_ancestor": row.get("known_good_is_ancestor"),
                "fixture_success": row.get("fixture_success"),
            }
            for row in report.get("fixtures") or []
        ],
        "scored_from": report.get("scored_from") or "trace-v1",
    }


def append_index(report: dict[str, Any], path: Path | None = None) -> Path:
    dest = path or INDEX_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    row = index_row(report)
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return dest
