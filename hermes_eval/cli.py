"""hermes-eval CLI: run one fixture or compare two Hermes refs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evals.scorers.canary import interpret_canary
from hermes_eval.canary_index import append_index
from hermes_eval.compare import build_compare, write_compare
from hermes_eval.fixtureload import FIXTURE_SCHEMA_VERSION, load_fixture, load_manifest
from hermes_eval.freeze import freeze_payload, write_freeze
from hermes_eval.trace.model import validate_trace
from hermes_eval.trace.rescore import emit_trace, result_from_trace, score_trace
from hermes_eval.gitutil import (
    REPO_ROOT,
    discover_python,
    expand_ref,
    fetch_moving_ref,
    fetch_shas,
    harness_git_state,
    historical_shas,
    provenance,
    resolve_hermes_root,
    sut_cache_dir,
)

FIXTURES = {
    "zero-toolset": REPO_ROOT / "evals" / "runners" / "zero_toolset.py",
    "zero-toolset-live": REPO_ROOT / "evals" / "runners" / "zero_toolset_live.py",
    "delegate-fallback-runtime": REPO_ROOT / "evals" / "runners" / "delegate_fallback.py",
    "stale-pin-rescope": REPO_ROOT / "evals" / "runners" / "stale_pin.py",
    "compression-prefix-probe": REPO_ROOT / "evals" / "runners" / "compression_probe.py",
}

SUITES = {
    "core-failures": [
        "zero-toolset",
        "delegate-fallback-runtime",
        "stale-pin-rescope",
    ]
}


def _python() -> str:
    return discover_python()


def _load_result(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _stamp_result(payload: dict, *, hermes_root: Path, sha: str, fixture: str, extra: dict) -> dict:
    spec = {}
    try:
        spec = load_fixture(fixture)
    except FileNotFoundError:
        spec = {"id": fixture, "version": payload.get("fixture_version") or 1}
    git_state = harness_git_state()
    payload["fixture"] = fixture
    payload["fixture_version"] = spec.get("version") or payload.get("fixture_version") or 1
    payload["fixture_schema_version"] = spec.get("schema_version") or FIXTURE_SCHEMA_VERSION
    payload["classification"] = spec.get("classification") or payload.get("classification")
    payload["hermes_ref"] = sha
    payload["harness_sha"] = git_state["harness_sha"]
    payload["harness_dirty"] = git_state["harness_dirty"]
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    payload["provenance"] = provenance(
        hermes_root,
        sha,
        extra={
            "fixture": fixture,
            "fixture_version": payload["fixture_version"],
            "fixture_schema_version": payload["fixture_schema_version"],
            "classification": payload.get("classification"),
            **extra,
        },
    )
    return payload


def run_fixture(
    fixture: str,
    ref: str,
    *,
    source: Path | None = None,
    out_dir: Path | None = None,
    python: str | None = None,
    extra_args: list[str] | None = None,
) -> Path:
    if fixture not in FIXTURES:
        raise SystemExit(f"unknown fixture {fixture!r}; known: {sorted(FIXTURES)}")
    hermes_root, sha = resolve_hermes_root(ref, source)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = out_dir or (REPO_ROOT / "results" / stamp / fixture / sha)
    dest.mkdir(parents=True, exist_ok=True)
    result_path = dest / "result.json"
    cmd = [
        python or _python(),
        str(FIXTURES[fixture]),
        "--hermes-root",
        str(hermes_root),
        "--hermes-sha",
        sha,
        "--out",
        str(result_path),
    ]
    if extra_args:
        cmd.extend(extra_args)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT), str(hermes_root), env.get("PYTHONPATH", "")]
    )
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    if not result_path.is_file():
        result_path.write_text(
            json.dumps(
                {
                    "fixture": fixture,
                    "hermes_ref": sha,
                    "success": False,
                    "notes": [
                        "runner produced no result.json",
                        f"exit={proc.returncode}",
                        (proc.stderr or proc.stdout or "")[-800:],
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    payload = _load_result(result_path)
    payload = _stamp_result(
        payload,
        hermes_root=hermes_root,
        sha=sha,
        fixture=fixture,
        extra={
            "python": python or _python(),
            "runner_exit": proc.returncode,
        },
    )
    if proc.returncode not in (0, 1) and proc.stderr:
        payload.setdefault("notes", []).append(f"runner stderr: {proc.stderr[-400:]}")
    payload = _attach_trace(result_path, payload)
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return result_path


def _attach_trace(result_path: Path, payload: dict) -> dict:
    """Write TraceV1 beside result.json. result.extras stay on disk for debug."""
    trace = emit_trace(payload)
    errors = validate_trace(trace)
    trace_path = result_path.parent / "trace.json"
    trace_path.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    payload["trace_path"] = str(trace_path)
    payload["trace_errors"] = errors
    scored = score_trace(trace)
    payload["runner_success"] = payload.get("success")
    payload["trace_success"] = bool(scored.get("success"))
    payload["trace_score"] = scored
    payload["trace_agreement"] = payload["runner_success"] == payload["trace_success"]
    if errors:
        payload.setdefault("notes", []).append("TraceV1 validation: " + "; ".join(errors[:6]))
    return payload


def _compare_payload(result_path: Path, *, from_trace: bool) -> dict:
    result = _load_result(result_path)
    if not from_trace:
        return result
    trace_path = result_path.parent / "trace.json"
    if not trace_path.is_file():
        result = _attach_trace(result_path, result)
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    scored = result_from_trace(trace, hermes_ref=result.get("hermes_ref"))
    scored["runner_success"] = result.get("runner_success", result.get("success"))
    scored["trace_agreement"] = result.get("trace_agreement")
    scored["harness_sha"] = result.get("harness_sha")
    scored["fixture_version"] = result.get("fixture_version")
    return scored


def cmd_run(args: argparse.Namespace) -> int:
    path = run_fixture(
        args.fixture,
        args.ref,
        source=Path(args.hermes_source) if args.hermes_source else None,
        out_dir=Path(args.out) if args.out else None,
        python=args.python,
    )
    result = _load_result(path)
    print(json.dumps(result, indent=2))
    sys.stderr.write(
        f"\n{result.get('fixture')} @ {result.get('hermes_ref')} "
        f"{'PASS' if result.get('success') else 'FAIL'} → {path}\n"
    )
    return 0 if result.get("success") else 1


def cmd_compare(args: argparse.Namespace) -> int:
    from_trace = not getattr(args, "runner_score", False)
    fixtures = SUITES.get(args.suite)
    if not fixtures:
        raise SystemExit(f"unknown suite {args.suite!r}; known: {sorted(SUITES)}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else (
        REPO_ROOT / "results" / f"compare-{args.suite}-{stamp}"
    )
    pairs = []
    labels = []
    for fixture in fixtures:
        spec = load_fixture(fixture)
        if args.historical:
            baseline, candidate = spec.get("known_bad"), spec.get("known_good")
            if not baseline or not candidate:
                raise SystemExit(f"{fixture} missing known_bad/known_good")
        else:
            baseline, candidate = args.baseline, args.candidate
        if not baseline or not candidate:
            raise SystemExit("compare requires --baseline and --candidate, or --historical")
        baseline = expand_ref(baseline)
        candidate = expand_ref(candidate)
        labels.append((fixture, baseline, candidate))
        base_path = run_fixture(
            fixture,
            baseline,
            source=Path(args.hermes_source) if args.hermes_source else None,
            out_dir=out_dir / "baseline" / fixture,
            python=args.python,
        )
        cand_path = run_fixture(
            fixture,
            candidate,
            source=Path(args.hermes_source) if args.hermes_source else None,
            out_dir=out_dir / "candidate" / fixture,
            python=args.python,
        )
        pairs.append(
            (
                _compare_payload(base_path, from_trace=from_trace),
                _compare_payload(cand_path, from_trace=from_trace),
            )
        )
    report = build_compare(
        suite=args.suite,
        baseline="historical-per-fixture" if args.historical else expand_ref(args.baseline),
        candidate="historical-per-fixture" if args.historical else expand_ref(args.candidate),
        pairs=pairs,
        harness_sha=harness_git_state()["harness_sha"],
        fixture_schema_version=FIXTURE_SCHEMA_VERSION,
        historical=bool(args.historical),
    )
    report["scored_from"] = "trace-v1" if from_trace else "runner"
    report["manifest"] = str(REPO_ROOT / "evals" / "provenance" / "manifest.json")
    if args.historical:
        report["per_fixture_refs"] = [
            {"fixture": f, "known_bad": b, "known_good": c} for f, b, c in labels
        ]
    disagreements = []
    for row, (b, c) in zip(report.get("fixtures") or [], pairs):
        if from_trace and (b.get("trace_agreement") is False or c.get("trace_agreement") is False):
            disagreements.append(row.get("fixture"))
    report["trace_runner_disagreements"] = disagreements
    if disagreements:
        report.setdefault("historical_validation", {}).setdefault("failures", []).append(
            "trace vs runner success disagreed: " + ", ".join(disagreements)
        )
        report["historical_validation"]["passed"] = False
    json_path, md_path = write_compare(report, out_dir)
    print(json.dumps(report, indent=2))
    sys.stderr.write(f"\n{md_path.read_text(encoding='utf-8')}\nJSON: {json_path}\n")
    return 0 if report["historical_validation"]["passed"] else 2


def cmd_scan(args: argparse.Namespace) -> int:
    script = REPO_ROOT / "evals" / "runners" / "wasted_turns.py"
    cmd = [args.python or _python(), str(script), str(args.path)]
    if args.out:
        cmd.extend(["--out", str(args.out)])
    if getattr(args, "label_sheet", False):
        cmd.append("--label-sheet")
    return subprocess.call(cmd, cwd=str(REPO_ROOT))


def cmd_live(args: argparse.Namespace) -> int:
    path = run_fixture(
        "zero-toolset-live",
        args.ref,
        source=Path(args.hermes_source) if args.hermes_source else None,
        out_dir=Path(args.out) if args.out else None,
        python=args.python,
        extra_args=["--reps", str(args.reps)],
    )
    result = _load_result(path)
    print(json.dumps(result, indent=2))
    status = result.get("status") or ("PASS" if result.get("success") else "FAIL")
    sys.stderr.write(f"\nzero-toolset-live @ {result.get('hermes_ref')} {status} → {path}\n")
    if result.get("status") == "BLOCKED":
        return 3
    if result.get("status") == "RUN":
        return 0
    return 0 if result.get("success") else 1


def cmd_probe_prefix(args: argparse.Namespace) -> int:
    path = run_fixture(
        "compression-prefix-probe",
        args.ref,
        source=Path(args.hermes_source) if args.hermes_source else None,
        out_dir=Path(args.out) if args.out else None,
        python=args.python,
    )
    result = _load_result(path)
    print(json.dumps(result, indent=2))
    sys.stderr.write(f"\ncompression-prefix-probe → {path}\n")
    return 0 if result.get("success") else 1


def cmd_manifest(args: argparse.Namespace) -> int:
    print(json.dumps(load_manifest(), indent=2))
    git_state = harness_git_state()
    sys.stderr.write(
        f"harness_sha={git_state['harness_sha']} dirty={git_state['harness_dirty']}\n"
    )
    return 0 if git_state["harness_sha"] else 1


def cmd_fetch_sut(args: argparse.Namespace) -> int:
    shas = list(args.sha) if args.sha else historical_shas()
    if args.current:
        current = fetch_moving_ref("refs/heads/main")
        shas.append(current)
    fetched = fetch_shas(shas)
    payload = {
        "cache": str(sut_cache_dir()),
        "fetched": fetched,
        "remotes": None,
    }
    from hermes_eval.gitutil import sut_remotes

    payload["remotes"] = sut_remotes()
    print(json.dumps(payload, indent=2))
    sys.stderr.write(f"fetched {len(fetched)} SHA(s) into {sut_cache_dir()}\n")
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    dest = write_freeze(Path(args.out) if args.out else None)
    payload = freeze_payload()
    print(json.dumps(payload, indent=2))
    sys.stderr.write(f"freeze → {dest}\n")
    return 0


def _render_canary_md(report: dict) -> str:
    lines = [
        "# Current canary",
        "",
        f"- Resolved current Hermes SHA: `{report.get('current_sha')}`",
        f"- Harness: `{report.get('harness_sha')}` dirty={report.get('harness_dirty')}",
        f"- When: {report.get('timestamp')}",
        "",
        "| Fixture | Resolved current Hermes SHA | Status | Reason |",
        "|---|---|---|---|",
    ]
    for row in report.get("fixtures") or []:
        reason = str(row.get("reason") or "").replace("|", "/")
        lines.append(
            f"| {row.get('fixture')} | `{row.get('current_sha')}` | "
            f"{row.get('status')} | {reason} |"
        )
    lines.append("")
    lines.append(
        "REGRESSION is recorded only when `known_good` is an ancestor of "
        "the resolved current SHA **and** the fixture failed. "
        "`FIX_NOT_ON_THIS_SHA` / `PASS_WITHOUT_FIX_SHA` are not regressions."
    )
    lines.append("")
    return "\n".join(lines)


def cmd_canary(args: argparse.Namespace) -> int:
    current = fetch_moving_ref("refs/heads/main")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else (REPO_ROOT / "results" / f"canary-{stamp}")
    rows = []
    for fixture in SUITES["core-failures"]:
        path = run_fixture(
            fixture,
            current,
            source=Path(args.hermes_source) if args.hermes_source else None,
            out_dir=out_dir / fixture,
            python=args.python,
        )
        result = _load_result(path)
        success = result.get("trace_success", result.get("success"))
        rows.append(
            interpret_canary(
                fixture=fixture,
                current_sha=current,
                success=bool(success),
            )
        )
    git_state = harness_git_state()
    report = {
        "current_sha": current,
        "harness_sha": git_state["harness_sha"],
        "harness_dirty": git_state["harness_dirty"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fixtures": rows,
        "scored_from": "trace-v1",
        "false_regression_rule": (
            "REGRESSION only if known_good is an ancestor AND the fixture failed"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "canary.json"
    md_path = out_dir / "canary.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_canary_md(report), encoding="utf-8")
    if not getattr(args, "no_index", False):
        idx = append_index(report)
        report["index"] = str(idx)
        json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    sys.stderr.write(f"\n{md_path.read_text(encoding='utf-8')}\nJSON: {json_path}\n")
    if any(r.get("status") == "REGRESSION" for r in rows):
        return 2
    return 0


def cmd_trace_emit(args: argparse.Namespace) -> int:
    src = Path(args.result)
    result = _load_result(src)
    dest = Path(args.out) if args.out else src.parent / "trace.json"
    trace = emit_trace(result)
    dest.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    scored = score_trace(trace)
    print(json.dumps({"trace": str(dest), "score": scored, "errors": validate_trace(trace)}, indent=2))
    return 0 if not validate_trace(trace) else 1


def cmd_trace_rescore(args: argparse.Namespace) -> int:
    trace = json.loads(Path(args.trace).read_text(encoding="utf-8"))
    scored = score_trace(trace)
    print(json.dumps(scored, indent=2))
    return 0 if scored.get("success") else 1


def cmd_trace_atof(args: argparse.Namespace) -> int:
    from hermes_eval.trace.adapters.atof import emit_atof

    trace = emit_atof(args.path)
    dest = Path(args.out) if args.out else Path(args.path).with_suffix(".trace.json")
    dest.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    errors = validate_trace(trace)
    print(json.dumps({"trace": str(dest), "metrics": trace.get("metrics"), "errors": errors}, indent=2))
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hermes-eval",
        description="External Hermes agent-behavior eval harness (research).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run one fixture against one Hermes ref")
    run_p.add_argument("--fixture", required=True, choices=sorted(FIXTURES))
    run_p.add_argument("--ref", required=True, help="Full SHA (aliases expand via provenance manifest)")
    run_p.add_argument("--hermes-source", help="Local git repo that contains the SHA")
    run_p.add_argument("--out")
    run_p.add_argument("--python")
    run_p.set_defaults(func=cmd_run)

    cmp_p = sub.add_parser("compare", help="Baseline vs candidate on a suite")
    cmp_p.add_argument("--baseline")
    cmp_p.add_argument("--candidate")
    cmp_p.add_argument(
        "--historical",
        action="store_true",
        help="Use each fixture YAML known_bad/known_good pair",
    )
    cmp_p.add_argument("--suite", default="core-failures")
    cmp_p.add_argument("--hermes-source")
    cmp_p.add_argument("--out")
    cmp_p.add_argument("--python")
    cmp_p.add_argument(
        "--runner-score",
        action="store_true",
        help="Score from runner extras instead of TraceV1 (escape hatch)",
    )
    cmp_p.set_defaults(func=cmd_compare)

    scan_p = sub.add_parser("scan-waste", help="Parse transcripts for waste candidates")
    scan_p.add_argument("path")
    scan_p.add_argument("--out")
    scan_p.add_argument("--python")
    scan_p.add_argument("--label-sheet", action="store_true")
    scan_p.set_defaults(func=cmd_scan)

    live_p = sub.add_parser("live", help="Live weak-model zero-toolset (BLOCKED without HERMES_EVAL_*)")
    live_p.add_argument("--ref", required=True)
    live_p.add_argument("--reps", type=int, default=int(os.environ.get("HERMES_EVAL_REPS", "5")))
    live_p.add_argument("--hermes-source")
    live_p.add_argument("--out")
    live_p.add_argument("--python")
    live_p.set_defaults(func=cmd_live)

    prefix_p = sub.add_parser("probe-prefix", help="Hash outgoing request prefixes (no Hermes core edits)")
    prefix_p.add_argument("--ref", required=True)
    prefix_p.add_argument("--hermes-source")
    prefix_p.add_argument("--out")
    prefix_p.add_argument("--python")
    prefix_p.set_defaults(func=cmd_probe_prefix)

    man_p = sub.add_parser("manifest", help="Print provenance manifest + harness SHA")
    man_p.set_defaults(func=cmd_manifest)

    fetch_p = sub.add_parser("fetch-sut", help="Fetch historical Hermes SHAs into .cache/hermes-sut")
    fetch_p.add_argument("sha", nargs="*", help="SHAs to fetch (default: known_bad + known_good)")
    fetch_p.add_argument(
        "--current",
        action="store_true",
        help="Also fetch refs/heads/main and record its full SHA",
    )
    fetch_p.set_defaults(func=cmd_fetch_sut)

    freeze_p = sub.add_parser("freeze", help="Write fixture SHA-256 digests")
    freeze_p.add_argument("--out")
    freeze_p.set_defaults(func=cmd_freeze)

    canary_p = sub.add_parser(
        "canary",
        help="Run the three core fixtures vs resolved origin/main SHA (no false regressions)",
    )
    canary_p.add_argument("--hermes-source")
    canary_p.add_argument("--out")
    canary_p.add_argument("--python")
    canary_p.add_argument("--no-index", action="store_true", help="Do not append evals/provenance/canary-index.jsonl")
    canary_p.set_defaults(func=cmd_canary)

    trace_p = sub.add_parser("trace", help="Emit or re-score TraceV1 logs")
    trace_sub = trace_p.add_subparsers(dest="trace_cmd", required=True)
    emit_p = trace_sub.add_parser("emit", help="Convert result.json → trace.json")
    emit_p.add_argument("--result", required=True)
    emit_p.add_argument("--out")
    emit_p.set_defaults(func=cmd_trace_emit)
    rescore_p = trace_sub.add_parser("rescore", help="Score a trace.json (ignores runner extras)")
    rescore_p.add_argument("--trace", required=True)
    rescore_p.set_defaults(func=cmd_trace_rescore)
    atof_p = trace_sub.add_parser("atof", help="Convert ATOF json/jsonl → TraceV1")
    atof_p.add_argument("path")
    atof_p.add_argument("--out")
    atof_p.set_defaults(func=cmd_trace_atof)
    return p


def main(argv: list[str] | None = None) -> int:
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    args = build_parser().parse_args(argv)
    return args.func(args)
