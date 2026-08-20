"""Compare two Hermes refs. Component metrics only — no magic score."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.scorers.score import compare_pair
from hermes_eval.fixtureload import FIXTURE_SCHEMA_VERSION, load_expected_historical
from hermes_eval.gitutil import harness_git_state


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Compare {report.get('suite')}",
        "",
        f"- Baseline: `{report.get('baseline')}`",
        f"- Candidate: `{report.get('candidate')}`",
        f"- Harness: `{report.get('harness_sha')}`",
        f"- Fixture schema: `{report.get('fixture_schema_version')}`",
        f"- When: {report.get('timestamp')}",
        "",
        "| Fixture | Known bad | Known good | Baseline | Candidate | Distinguished | Direction | Flags |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report.get("fixtures", []):
        flags = ", ".join(row.get("flags") or []) or "—"
        lines.append(
            "| {fixture} | `{bad}` | `{good}` | {b} | {c} | {d} | {dir} | {flags} |".format(
                fixture=row.get("fixture"),
                bad=(row.get("baseline_ref") or "")[:12],
                good=(row.get("candidate_ref") or "")[:12],
                b="PASS" if row.get("baseline_success") else "FAIL",
                c="PASS" if row.get("candidate_success") else "FAIL",
                d="yes" if row.get("distinguished") else "no",
                dir=row.get("direction"),
                flags=flags,
            )
        )
    lines.append("")
    gate = report.get("historical_validation") or {}
    lines.append("## Historical validation gate")
    lines.append("")
    lines.append(
        f"Fixtures that distinguished known-bad from known-good: "
        f"**{gate.get('distinguished_count', 0)}** / {gate.get('compared', 0)}"
    )
    lines.append(
        f"Frozen expected splits identical: "
        f"**{gate.get('expected_identical_count', 0)}** / {gate.get('compared', 0)}"
    )
    if gate.get("passed"):
        lines.append("")
        lines.append(
            "Gate: **PASSED** (3/3 distinguished and identical to frozen expected splits)."
        )
    else:
        lines.append("")
        lines.append(
            "Gate: **FAILED** (need every suite fixture to separate known-bad "
            "from known-good with the frozen success polarity)."
        )
        for note in gate.get("failures") or []:
            lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _expected_by_fixture() -> dict[str, dict[str, Any]]:
    payload = load_expected_historical()
    return {row["fixture"]: row for row in payload.get("fixtures") or []}


def _match_expected(row: dict[str, Any], expected: dict[str, Any] | None) -> tuple[bool, list[str]]:
    if expected is None:
        return False, ["no frozen expected row"]
    misses = []
    mapping = {
        "baseline_success": row.get("baseline_success"),
        "candidate_success": row.get("candidate_success"),
        "direction": row.get("direction"),
        "distinguished": row.get("distinguished"),
        "known_bad": row.get("baseline_ref"),
        "known_good": row.get("candidate_ref"),
    }
    for key, got in mapping.items():
        want = expected.get(key)
        if got != want:
            misses.append(f"{key}: got {got!r} want {want!r}")
    return not misses, misses


def build_compare(
    *,
    suite: str,
    baseline: str,
    candidate: str,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    harness_sha: str | None,
    fixture_schema_version: int | None = None,
    historical: bool = False,
) -> dict[str, Any]:
    rows = [compare_pair(b, c) for b, c in pairs]
    distinguished = sum(1 for row in rows if row.get("distinguished"))
    expected_map = _expected_by_fixture() if historical else {}
    identical = 0
    failures: list[str] = []
    for row in rows:
        exp = expected_map.get(row.get("fixture"))
        ok, misses = _match_expected(row, exp) if historical else (True, [])
        row["matches_frozen_expected"] = ok if historical else None
        if ok:
            identical += 1
        elif historical:
            failures.append(f"{row.get('fixture')}: " + "; ".join(misses))
        if historical and row.get("direction") != "candidate_fixed":
            failures.append(
                f"{row.get('fixture')}: direction is {row.get('direction')}, want candidate_fixed"
            )
    git_state = harness_git_state()
    compared = len(rows)
    passed = (
        compared > 0
        and distinguished == compared
        and all(row.get("direction") == "candidate_fixed" for row in rows)
        and (identical == compared if historical else True)
    )
    report = {
        "suite": suite,
        "baseline": baseline,
        "candidate": candidate,
        "harness_sha": harness_sha or git_state["harness_sha"],
        "harness_dirty": git_state["harness_dirty"],
        "fixture_schema_version": fixture_schema_version or FIXTURE_SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fixtures": rows,
        "historical_validation": {
            "compared": compared,
            "distinguished_count": distinguished,
            "expected_identical_count": identical if historical else None,
            "passed": passed,
            "require": (
                "all fixtures distinguished candidate_fixed; "
                "historical also matches frozen expected splits"
            ),
            "failures": failures,
        },
    }
    return report


def write_compare(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "compare.json"
    md_path = out_dir / "compare.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
