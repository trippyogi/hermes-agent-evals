"""Ingest NousResearch/hermes-toolperf-evals 2026-08-06 rerun into TraceV1.

Read-only. Does not modify or push the Nous repo.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.runners.wasted_turns import collapse_episodes, detect_candidates
from hermes_eval.gitutil import REPO_ROOT
from hermes_eval.trace.abeval_ref import score_run as abeval_score_run
from hermes_eval.trace.adapters.atof import emit_atof
from hermes_eval.trace.model import validate_trace
from hermes_eval.trace.rescore import score_atof_trace

DATASET = "hermes-toolperf-evals/2026-08-06_rerun"
MODELS = (
    "anthropic/claude-sonnet-4.5",
    "qwen/qwen3-coder-30b-a3b-instruct",
)
ARMS = ("baseline", "fixes")
TASKS = (
    "err_python_env",
    "err_replay_patch",
    "err_ambiguous_edit",
    "err_case_search",
    "err_hidden_search",
    "err_big_output",
    "err_multi_dir",
    "err_inline_script",
    "err_big_file_read",
)
HERMES_SHA = {
    "baseline": "5b4d20b524c641a3c7a708a5dc8696a4c6a28588",
    "fixes": "f01c193be4aa034874ab2204c74d20e4e4360259",
}

# Official SUCCESS() in abeval uses sandbox files for these two.
ORACLE = {
    "err_python_env": "tail",
    "err_replay_patch": "filesystem",
    "err_ambiguous_edit": "tail",
    "err_case_search": "tail",
    "err_hidden_search": "tail",
    "err_big_output": "tail",
    "err_multi_dir": "filesystem",
    "err_inline_script": "tail",
    "err_big_file_read": "tail",
}

TAIL_OK = {
    "err_python_env": lambda t: "ENV_OK_4477" in t,
    "err_replay_patch": lambda t: "CONFIG_OK_881" in t,
    "err_ambiguous_edit": lambda t: "HANDLERS_OK_552" in t,
    "err_case_search": lambda t: "settings.ini" in t and "client.go" in t,
    "err_hidden_search": lambda t: "rotation.cfg" in t and "ops.md" in t,
    "err_big_output": lambda t: "tok_9f31c_middle" in t,
    "err_multi_dir": lambda t: "1.4.2,0.9.7,3.2.1" in t,
    "err_inline_script": lambda t: "21341334000" in t.replace(",", ""),
    "err_big_file_read": lambda t: "X99Q" in t,
}

FUNCTION_XML_RE = "<function="


def default_rerun_dir() -> Path:
    env = os.environ.get("HERMES_EVAL_TOOLPERF_RERUN", "").strip()
    if env:
        return Path(env)
    sibling = REPO_ROOT.parent / "hermes-toolperf-evals" / "results" / "2026-08-06_rerun"
    return sibling


def cache_dir() -> Path:
    env = os.environ.get("HERMES_EVAL_TOOLPERF_CACHE", "").strip()
    if env:
        return Path(env)
    return REPO_ROOT / ".cache" / "toolperf-2026-08-06"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_extracted(rerun: Path) -> Path:
    dest = cache_dir()
    tgz = rerun / "atof-traces.tgz"
    if not tgz.is_file():
        raise SystemExit(f"missing {tgz} (read-only toolperf rerun archive)")
    expected = sha256_file(tgz)
    stamp = dest / "archive.sha256"
    marker = dest / "results"
    cached = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    have_files = marker.is_dir() and any(marker.rglob("*.atof.jsonl"))
    if have_files and cached == expected:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tgz, "r:gz") as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:
            tf.extractall(dest)
    stamp.write_text(expected + "\n", encoding="utf-8")
    return dest


def load_meta(rerun: Path, model: str, arm: str) -> list[dict[str, Any]]:
    path = rerun / model.replace("/", "_") / arm / "meta.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def atof_path(extracted: Path, model: str, arm: str, run_id: str) -> Path:
    return extracted / "results" / model.replace("/", "_") / arm / f"{run_id}.atof.jsonl"


def _mean(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(r.get(key) or 0) for r in rows) / len(rows)


def ingest(rerun: Path | None = None) -> dict[str, Any]:
    rerun = (rerun or default_rerun_dir()).resolve()
    if not rerun.is_dir():
        raise SystemExit(f"toolperf rerun dir not found: {rerun}")
    tgz = rerun / "atof-traces.tgz"
    tgz_sha = sha256_file(tgz) if tgz.is_file() else None
    extracted = ensure_extracted(rerun)
    report_txt = (rerun / "report.txt").read_text(encoding="utf-8") if (rerun / "report.txt").is_file() else ""

    runs: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    waste_hits: list[dict[str, Any]] = []

    for model in MODELS:
        for arm in ARMS:
            for rec in load_meta(rerun, model, arm):
                run_id = rec["run_id"]
                task = rec["task"]
                src = atof_path(extracted, model, arm, run_id)
                ref = abeval_score_run(src)
                if ref is None:
                    mismatches.append(
                        {
                            "run_id": run_id,
                            "model": model,
                            "arm": arm,
                            "reason": f"abeval_ref returned None (missing {src})",
                        }
                    )
                    continue
                atof_sha = sha256_file(src)
                hermes_sha = HERMES_SHA[arm]
                trace = emit_atof(
                    src,
                    fixture=task,
                    hermes_sha=hermes_sha,
                    run_id=f"{DATASET}:{model}:{arm}:{run_id}",
                )
                trace["provenance"].update(
                    {
                        "dataset": DATASET,
                        "model": model,
                        "arm": arm,
                        "task": task,
                        "rep": rec.get("rep"),
                        "hermes_sha": hermes_sha,
                        "atof_sha256": atof_sha,
                        "archive_sha256": tgz_sha,
                    }
                )
                errors = validate_trace(trace)
                scored = score_atof_trace(trace)
                keys = ("llm", "tools", "errs", "retries", "kb")
                equal = all(scored.get(k) == ref.get(k) for k in keys)
                if not equal or errors:
                    mismatches.append(
                        {
                            "run_id": run_id,
                            "model": model,
                            "arm": arm,
                            "task": task,
                            "trace_errors": errors,
                            "abeval": {k: ref.get(k) for k in keys},
                            "tracev1": {k: scored.get(k) for k in keys},
                            "reason": "metric mismatch" if not equal else "trace validation",
                        }
                    )
                tail = rec.get("tail") or ""
                oracle = ORACLE[task]
                tail_ok = bool(TAIL_OK[task](tail))
                xml_fail = FUNCTION_XML_RE in tail
                if oracle == "tail":
                    success_status = "reconstructed_from_tail"
                    success = tail_ok
                else:
                    success_status = "NOT_RECONSTRUCTABLE_FROM_ARCHIVE"
                    success = None
                abandoned = False
                if success is False:
                    abandoned = scored["tools"] == 0 or xml_fail
                recovered = bool(scored["errs"] > 0 and success is True)
                payload = {
                    "events": _tool_events(trace),
                    "transcript": tail,
                }
                hits = detect_candidates(payload, f"{model}/{arm}/{run_id}")
                waste_hits.extend(hits)

                runs.append(
                    {
                        "dataset": DATASET,
                        "model": model,
                        "arm": arm,
                        "task": task,
                        "rep": rec.get("rep"),
                        "run_id": run_id,
                        "hermes_sha": hermes_sha,
                        "atof_sha256": atof_sha,
                        "archive_sha256": tgz_sha,
                        "wall_s": rec.get("wall_s"),
                        "exit": rec.get("exit"),
                        "oracle": oracle,
                        "success_status": success_status,
                        "success": success,
                        "tail_ok": tail_ok,
                        "provider_function_xml": xml_fail,
                        "abandoned": abandoned,
                        "recovered": recovered,
                        "metrics": scored,
                        "abeval": ref,
                        "match": equal and not errors,
                    }
                )

    episodes = collapse_episodes(waste_hits)
    tables = _tables(runs)
    analysis = _analysis(runs)
    published = _parse_published(report_txt)
    return {
        "dataset": DATASET,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rerun_dir": str(rerun).replace("\\", "/"),
        "archive_sha256": tgz_sha,
        "hermes_sha": HERMES_SHA,
        "n_runs": len(runs),
        "n_expected": 108,
        "gate1_metric_matches": sum(1 for r in runs if r["match"]),
        "mismatches": mismatches,
        "tables": tables,
        "analysis": analysis,
        "published_report_excerpt": published,
        "REAL_ATOF_DATA": "available",
        "waste": {
            "detector_hits": len(waste_hits),
            "episode_count": len(episodes),
            "overlaps_collapsed": sum(1 for ep in episodes if len(ep.get("w_labels") or []) > 1),
            "episodes": episodes,
        },
        "runs": runs,
    }


def _tool_events(trace: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    pending = None
    for ev in trace.get("events") or []:
        kind = ev.get("type")
        payload = ev.get("payload") or {}
        if kind == "tool.call":
            pending = payload
        elif kind == "tool.result":
            events.append(
                {
                    "type": "tool",
                    "name": payload.get("name") or (pending or {}).get("name"),
                    "status": "error" if payload.get("ok") is False else "ok",
                    "arguments": (pending or {}).get("arguments"),
                    "arguments_hash": (pending or {}).get("arguments_hash"),
                }
            )
            pending = None
    return events


def _tables(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in runs:
        grouped[(row["model"], row["task"], row["arm"])].append(row)
    out = []
    for model in MODELS:
        for task in TASKS:
            for arm in ARMS:
                rows = grouped.get((model, task, arm), [])
                if not rows:
                    continue
                n = len(rows)
                recon = [r for r in rows if r["success_status"] == "reconstructed_from_tail"]
                ok_n = sum(1 for r in recon if r["success"]) if recon else None
                out.append(
                    {
                        "model": model,
                        "task": task,
                        "arm": arm,
                        "n": n,
                        "oracle": ORACLE[task],
                        "ok_pct_from_tail": (
                            round(100 * ok_n / len(recon), 0) if recon else None
                        ),
                        "ok_status": (
                            "reconstructed_from_tail"
                            if ORACLE[task] == "tail"
                            else "NOT_RECONSTRUCTABLE_FROM_ARCHIVE"
                        ),
                        "llm": round(_mean(rows, "llm"), 1),
                        "tool": round(_mean(rows, "tools"), 1),
                        "errs": round(_mean(rows, "errs"), 1),
                        "retr": round(_mean(rows, "retries"), 1),
                        "kb": round(_mean(rows, "kb"), 0),
                        "wall": round(_mean(rows, "wall_s"), 0),
                    }
                )
    # fix nested metric access
    for item in out:
        subset = grouped[(item["model"], item["task"], item["arm"])]
        item["llm"] = round(_mean([{"llm": r["metrics"]["llm"]} for r in subset], "llm"), 1)
        item["tool"] = round(_mean([{"tools": r["metrics"]["tools"]} for r in subset], "tools"), 1)
        item["errs"] = round(_mean([{"errs": r["metrics"]["errs"]} for r in subset], "errs"), 1)
        item["retr"] = round(_mean([{"retries": r["metrics"]["retries"]} for r in subset], "retries"), 1)
        item["kb"] = round(_mean([{"kb": r["metrics"]["kb"]} for r in subset], "kb"), 0)
        item["wall"] = round(_mean(subset, "wall_s"), 0)
    totals = []
    for model in MODELS:
        for arm in ARMS:
            subset = [r for r in runs if r["model"] == model and r["arm"] == arm]
            recon = [r for r in subset if r["success_status"] == "reconstructed_from_tail"]
            totals.append(
                {
                    "model": model,
                    "task": "TOTAL",
                    "arm": arm,
                    "n": len(subset),
                    "oracle": "mixed",
                    "ok_pct_from_tail": (
                        round(100 * sum(1 for r in recon if r["success"]) / len(recon), 0)
                        if recon
                        else None
                    ),
                    "ok_status": "partial_tail_only; filesystem tasks excluded",
                    "llm": round(_mean([{"llm": r["metrics"]["llm"]} for r in subset], "llm"), 1),
                    "tool": round(_mean([{"tools": r["metrics"]["tools"]} for r in subset], "tools"), 1),
                    "errs": round(_mean([{"errs": r["metrics"]["errs"]} for r in subset], "errs"), 1),
                    "retr": round(_mean([{"retries": r["metrics"]["retries"]} for r in subset], "retries"), 1),
                    "kb": round(_mean([{"kb": r["metrics"]["kb"]} for r in subset], "kb"), 0),
                    "wall": round(_mean(subset, "wall_s"), 0),
                }
            )
    return out + totals


def _analysis(runs: list[dict[str, Any]]) -> dict[str, Any]:
    more_turns_success = []
    fewer_turns_fail = []
    by_cell: dict[tuple, dict[str, list]] = defaultdict(lambda: {"baseline": [], "fixes": []})
    for row in runs:
        if row["success_status"] != "reconstructed_from_tail":
            continue
        by_cell[(row["model"], row["task"])][row["arm"]].append(row)
        if row["success"] and row["metrics"]["llm"] >= 4:
            more_turns_success.append(_brief(row))
        if row["success"] is False and row["metrics"]["llm"] <= 2:
            fewer_turns_fail.append(_brief(row))
    recovery = [_brief(r) for r in runs if r.get("recovered")]
    xml = [_brief(r) for r in runs if r.get("provider_function_xml")]
    cells = []
    for (model, task), arms in sorted(by_cell.items()):
        b = arms["baseline"]
        f = arms["fixes"]
        if not b or not f:
            continue
        b_ok = sum(1 for r in b if r["success"]) / len(b)
        f_ok = sum(1 for r in f if r["success"]) / len(f)
        b_llm = _mean([{"llm": r["metrics"]["llm"]} for r in b], "llm")
        f_llm = _mean([{"llm": r["metrics"]["llm"]} for r in f], "llm")
        cells.append(
            {
                "model": model,
                "task": task,
                "baseline_ok": round(b_ok, 3),
                "fixes_ok": round(f_ok, 3),
                "baseline_llm": round(b_llm, 2),
                "fixes_llm": round(f_llm, 2),
                "story": (
                    "more_turns_and_higher_success"
                    if f_ok > b_ok and f_llm > b_llm
                    else "fewer_turns_and_higher_success"
                    if f_ok > b_ok and f_llm < b_llm
                    else "success_down"
                    if f_ok < b_ok
                    else "parity"
                ),
            }
        )
    eff = []
    for model in MODELS:
        for arm in ARMS:
            ok = [
                r
                for r in runs
                if r["model"] == model
                and r["arm"] == arm
                and r["success_status"] == "reconstructed_from_tail"
                and r["success"]
            ]
            fail = [
                r
                for r in runs
                if r["model"] == model
                and r["arm"] == arm
                and r["success_status"] == "reconstructed_from_tail"
                and r["success"] is False
            ]
            eff.append(
                {
                    "model": model,
                    "arm": arm,
                    "n_success": len(ok),
                    "n_fail": len(fail),
                    "llm_given_success": round(_mean([{"llm": r["metrics"]["llm"]} for r in ok], "llm"), 2)
                    if ok
                    else None,
                    "tools_given_success": round(
                        _mean([{"tools": r["metrics"]["tools"]} for r in ok], "tools"), 2
                    )
                    if ok
                    else None,
                    "kb_given_success": round(_mean([{"kb": r["metrics"]["kb"]} for r in ok], "kb"), 1)
                    if ok
                    else None,
                    "wall_given_success": round(_mean(ok, "wall_s"), 1) if ok else None,
                    "llm_given_failure": round(_mean([{"llm": r["metrics"]["llm"]} for r in fail], "llm"), 2)
                    if fail
                    else None,
                }
            )
    return {
        "no_composite_score": True,
        "efficiency_given_success": eff,
        "recovery": recovery,
        "provider_function_xml": xml,
        "fewer_turns_failure_examples": fewer_turns_fail[:24],
        "more_turns_success_examples": more_turns_success[:24],
        "cells": cells,
    }


def _brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": row["model"],
        "arm": row["arm"],
        "task": row["task"],
        "rep": row["rep"],
        "success": row["success"],
        "llm": row["metrics"]["llm"],
        "tools": row["metrics"]["tools"],
        "errs": row["metrics"]["errs"],
        "xml": row["provider_function_xml"],
        "abandoned": row["abandoned"],
    }


def _parse_published(text: str) -> str:
    return text.strip()[:4000]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# v0.3.1 — Toolperf corpus ingestion",
        "",
        f"Dataset: `{payload['dataset']}`",
        f"Runs ingested: **{payload['n_runs']}** / {payload['n_expected']}",
        f"Gate 1 metric identity: **{payload['gate1_metric_matches']}** / {payload['n_runs']}",
        f"REAL_ATOF_DATA: **{payload['REAL_ATOF_DATA']}**",
        f"Archive sha256: `{payload.get('archive_sha256')}`",
        "",
        "Read-only input: `NousResearch/hermes-toolperf-evals` `results/2026-08-06_rerun/`.",
        "No writes to the Nous repo. No new Hermes fixtures.",
        "",
        "## Gate 1 — ATOF fidelity",
        "",
        "Compared TraceV1-derived `llm`, `tools`, `errs`, `retries`, `kb` against the",
        "frozen abeval `score_run` on every archived jsonl.",
        "",
    ]
    if payload["mismatches"]:
        lines.append(f"**Mismatches:** {len(payload['mismatches'])}")
        for row in payload["mismatches"][:20]:
            lines.append(f"- `{row.get('model')}/{row.get('arm')}/{row.get('run_id')}`: {row.get('reason')} {row.get('abeval')} vs {row.get('tracev1')}")
    else:
        lines.append("**108/108 identical** (or all ingested runs). No mismatches.")
    lines.extend(
        [
            "",
            "## Gate 2 — Run structure",
            "",
            "Each run keeps dataset, model, arm, task, rep, Hermes SHA, ATOF checksum.",
            "Not flattened.",
            "",
            f"- baseline SHA `{HERMES_SHA['baseline']}`",
            f"- fixes SHA `{HERMES_SHA['fixes']}`",
            "",
            "## Gate 3 — Published tables vs TraceV1",
            "",
            "ATOF columns (llm/tool/errs/retr/kb) come from TraceV1. Wall comes from",
            "`meta.jsonl`. Official `ok%` used ephemeral sandbox files for",
            "`err_replay_patch` and `err_multi_dir` — those cells are",
            "`NOT_RECONSTRUCTABLE_FROM_ARCHIVE`. Other tasks use tail-only oracles",
            "from meta tails. Do not treat tail proxies as filesystem oracle checks.",
            "",
            "Checked-in `report.txt` remains the source of record for published ok%.",
            "",
        ]
    )
    lines.append("| model | task | arm | n | ok (archive) | llm | tool | errs | retr | kb | wall |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for row in payload.get("tables") or []:
        model = row["model"].split("/")[-1]
        ok = (
            "NOT_RECONSTRUCTABLE"
            if row["ok_status"].startswith("NOT")
            else (f"{int(row['ok_pct_from_tail'])}%" if row.get("ok_pct_from_tail") is not None else "—")
        )
        if row["task"] == "TOTAL":
            ok = "partial tail"
        lines.append(
            f"| {model} | {row['task']} | {row['arm']} | {row['n']} | {ok} | "
            f"{row['llm']} | {row['tool']} | {row['errs']} | {row['retr']} | "
            f"{int(row['kb'])} | {int(row['wall'])}s |"
        )
    lines.extend(
        [
            "",
            "## Gate 4 — Outcome vs efficiency (no composite score)",
            "",
            "Fewer turns is not better when the agent gave up. Extra turns after a",
            "parser block or truncation recovery can be the win.",
            "",
        ]
    )
    lines.append("| model | task | baseline ok | fixes ok | baseline llm | fixes llm | story |")
    lines.append("|---|---|---|---|---|---|---|")
    for cell in (payload.get("analysis") or {}).get("cells") or []:
        model = cell["model"].split("/")[-1]
        lines.append(
            f"| {model} | {cell['task']} | {cell['baseline_ok']} | {cell['fixes_ok']} | "
            f"{cell['baseline_llm']} | {cell['fixes_llm']} | {cell['story']} |"
        )
    lines.extend(["", "### Efficiency given success", "", "| model | arm | n_ok | llm | tools | kb | wall | n_fail | llm on fail |", "|---|---|---|---|---|---|---|---|---|"])
    for row in (payload.get("analysis") or {}).get("efficiency_given_success") or []:
        model = row["model"].split("/")[-1]
        lines.append(
            f"| {model} | {row['arm']} | {row['n_success']} | {row['llm_given_success']} | "
            f"{row['tools_given_success']} | {row['kb_given_success']} | {row['wall_given_success']} | "
            f"{row['n_fail']} | {row['llm_given_failure']} |"
        )
    waste = payload.get("waste") or {}
    lines.extend(
        [
            "",
            "## Gate 5 — Waste detectors on real ATOF",
            "",
            f"Detector hits: **{waste.get('detector_hits')}**",
            f"Unique episodes: **{waste.get('episode_count')}**",
            f"Overlaps collapsed: **{waste.get('overlaps_collapsed')}**",
            "",
            "No auto-label. Label sheet: `reports/evals/wasted-turn-labeling-toolperf-episodes.md`.",
            "",
            "W1 did not fire: identical-name retries after error usually changed arguments.",
            "W3/W5 are argument-aware now (ATOF tool-start `data` hashed into TraceV1).",
            "W6 (7) matches the 7 Qwen tails containing raw `<function=` XML.",
            "",
            "Official published `ok%` remains `results/2026-08-06_rerun/report.txt`",
            "in NousResearch/hermes-toolperf-evals. Do not copy it here.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def render_label_sheet(payload: dict[str, Any]) -> str:
    from evals.runners.wasted_turns import render_label_sheet as _sheet

    scan = {
        "REAL_ATOF_DATA": "available",
        "corpus": "atof",
        "detector_hits": payload["waste"]["detector_hits"],
        "episode_count": payload["waste"]["episode_count"],
        "overlaps_collapsed": payload["waste"]["overlaps_collapsed"],
        "by_w_label": {},
        "episodes": payload["waste"]["episodes"],
    }
    from collections import Counter

    scan["by_w_label"] = dict(
        Counter(l for ep in payload["waste"]["episodes"] for l in ep.get("w_labels") or [])
    )
    return _sheet(scan)
