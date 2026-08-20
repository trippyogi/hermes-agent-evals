"""v0.4.1 ATOF waste adjudication packet.

Human annotations live in a sidecar JSON, not in TraceV1.
Do not self-label. Do not expand the 13-episode corpus this pass.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_eval.gitutil import REPO_ROOT, harness_sha
from hermes_eval.redact import redact_obj, redact_text
from hermes_eval.toolperf_ingest import (
    DATASET,
    atof_path,
    default_rerun_dir,
    ensure_extracted,
    load_meta,
)
from hermes_eval.trace.adapters.atof import emit_atof

V0_4_SHA = "ce6297df337ab0dc1abc82e6c69f842c03431451"
ALLOWED_VERDICTS = ("waste", "not_waste", "unsure")
ALLOWED_RELATION = ("recovery", "neutral", "harmful", "unknown")
MAX_SNIPPET = 240
PACKET_VERSION = 1

DETECTOR_EVIDENCE = {
    "W1": "same name+args after a deterministic-looking failure",
    "W2": "event marked dead_runtime/session_dead",
    "W3": "identical retry with unchanged state token",
    "W4": "tool result immediately inverted by the next tool",
    "W5": "identical read with unchanged arguments",
    "W6": "transcript contains a JSON/XML tool call and events have zero structured tools",
}


def parse_source(source: str) -> tuple[str, str, str]:
    model, arm, run_id = source.rsplit("/", 2)
    return model, arm, run_id


def _snip(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = redact_obj(value)
    text = cleaned if isinstance(cleaned, str) else json.dumps(cleaned, ensure_ascii=False, default=str)
    text = redact_text(text).replace("\n", " ")
    if len(text) > MAX_SNIPPET:
        return text[: MAX_SNIPPET - 1] + "…"
    return text


def _run_for_source(runs: list[dict[str, Any]], source: str) -> dict[str, Any]:
    model, arm, run_id = parse_source(source)
    for row in runs:
        if row.get("model") == model and row.get("arm") == arm and row.get("run_id") == run_id:
            return row
    raise KeyError(source)


def _task_outcome(row: dict[str, Any]) -> str:
    if row.get("success_status") == "NOT_RECONSTRUCTABLE_FROM_ARCHIVE" or row.get("success") is None:
        return "unknown"
    return "success" if row.get("success") else "failure"


def walk_atof(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    starts: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("kind") != "scope":
            continue
        cat = ev.get("category")
        scope = ev.get("scope_category")
        name = ev.get("name")
        if cat == "llm" and scope == "end":
            events.append({"role": "llm", "name": name, "summary": "model.response"})
        elif cat == "tool" and scope == "start":
            starts.append(ev)
            events.append(
                {
                    "role": "tool_call",
                    "name": name,
                    "arguments": redact_obj(ev.get("data") if isinstance(ev.get("data"), dict) else None),
                    "summary": _snip(ev.get("data")),
                }
            )
        elif cat == "tool" and scope == "end":
            start = starts.pop(0) if starts else {}
            args = start.get("data") if isinstance(start.get("data"), dict) else None
            data = ev.get("data")
            status = (ev.get("metadata") or {}).get("status") or "ok"
            events.append(
                {
                    "role": "tool_result",
                    "name": name or start.get("name"),
                    "arguments": redact_obj(args) if args is not None else None,
                    "ok": status in (None, "ok"),
                    "status": status,
                    "summary": _snip(data),
                    "call_summary": _snip(args if args is not None else start.get("data")),
                }
            )
    return events


def _tool_actions(atof_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in atof_events:
        if ev.get("role") != "tool_result":
            continue
        out.append(
            {
                "name": ev.get("name"),
                "arguments": ev.get("arguments"),
                "ok": ev.get("ok"),
                "status": ev.get("status"),
                "result_summary": ev.get("summary"),
                "call_summary": ev.get("call_summary"),
            }
        )
    return out


def _window(items: list[dict[str, Any]], index: int | None, radius: int = 2) -> dict[str, Any]:
    if not items:
        return {"before": [], "candidate": [], "after": []}
    if index is None:
        return {"before": items[:radius], "candidate": items, "after": []}
    idx = max(0, min(index, len(items) - 1))
    return {
        "before": items[max(0, idx - radius) : idx],
        "candidate": [items[idx]],
        "after": items[idx + 1 : idx + 1 + radius],
    }


def _args_changed(prev: dict[str, Any] | None, cur: dict[str, Any] | None) -> bool | None:
    if not prev or not cur:
        return None
    return json.dumps(prev.get("arguments"), sort_keys=True, default=str) != json.dumps(
        cur.get("arguments"), sort_keys=True, default=str
    )


def build_episode(
    *,
    episode_id: str,
    ep: dict[str, Any],
    row: dict[str, Any],
    atof: Path,
    tail: str,
) -> dict[str, Any]:
    atof_events = walk_atof(atof)
    tools = _tool_actions(atof_events)
    idx = ep.get("index")
    if idx is None:
        window = {
            "before": atof_events[-2:],
            "candidate": [
                {
                    "name": None,
                    "role": "textual_pseudo_call",
                    "summary": _snip(tail),
                    "arguments": None,
                    "ok": None,
                }
            ],
            "after": [],
        }
    else:
        window = _window(tools, idx)
    current = (window["candidate"] or [None])[0]
    previous = window["before"][-1] if window["before"] else None
    labels = list(ep.get("w_labels") or [])
    error_occurred = False
    if current and current.get("ok") is False:
        error_occurred = True
    if any(t.get("ok") is False for t in tools):
        error_occurred = True
    remaining = 0
    if idx is not None and tools:
        remaining = max(0, len(tools) - (idx + 1))
    trace = emit_atof(atof, fixture=row["task"], hermes_sha=row["hermes_sha"], run_id=row["run_id"])
    hit_evidence = {label: DETECTOR_EVIDENCE.get(label) for label in labels}
    if ep.get("evidence"):
        hit_evidence["episode"] = ep.get("evidence")
    return {
        "episode_id": episode_id,
        "dataset": DATASET,
        "model": row["model"],
        "arm": row["arm"],
        "task": row["task"],
        "rep": row.get("rep"),
        "run_id": row["run_id"],
        "hermes_sha": row["hermes_sha"],
        "atof_sha256": row.get("atof_sha256"),
        "detectors": labels,
        "detector_hit_count": ep.get("hit_count"),
        "tool_name": ep.get("tool") or (current.get("name") if current else None),
        "tool_arguments_scrubbed": redact_obj((current or {}).get("arguments")),
        "previous_action": {
            "name": (previous or {}).get("name"),
            "arguments": redact_obj((previous or {}).get("arguments")),
            "summary": (previous or {}).get("call_summary") or (previous or {}).get("summary"),
        }
        if previous
        else None,
        "previous_result_summary": (previous or {}).get("result_summary") or (previous or {}).get("summary"),
        "current_action": {
            "name": (current or {}).get("name"),
            "arguments": redact_obj((current or {}).get("arguments")),
            "summary": (current or {}).get("call_summary") or (current or {}).get("summary"),
        }
        if current
        else None,
        "current_result_summary": (current or {}).get("result_summary") or (current or {}).get("summary"),
        "state_changed": ep.get("state_changed"),
        "args_changed": _args_changed(previous, current),
        "error_occurred": error_occurred,
        "task_outcome": _task_outcome(row),
        "task_outcome_note": row.get("success_status"),
        "candidate_relationship_to_outcome": None,
        "turns_remaining_after_candidate": remaining,
        "metrics": row.get("metrics"),
        "provider_function_xml": row.get("provider_function_xml"),
        "abandoned": row.get("abandoned"),
        "trajectory": window,
        "atof_tool_actions": tools,
        "final_output_tail": _snip(tail),
        "detector_evidence": hit_evidence,
        "HUMAN_VERDICT": None,
        "HUMAN_REASON": None,
        "trace_run_id": trace.get("run_id"),
    }


def build_packet(ingest: dict[str, Any], rerun: Path | None = None) -> dict[str, Any]:
    rerun = (rerun or default_rerun_dir()).resolve()
    extracted = ensure_extracted(rerun)
    waste = ingest.get("waste") or {}
    episodes_in = waste.get("episodes") or []
    if len(episodes_in) != 13:
        raise SystemExit(f"expected 13 unique episodes, found {len(episodes_in)}")
    hits = waste.get("detector_hits")
    if hits != 19:
        raise SystemExit(f"expected 19 detector hits, found {hits}")
    built: list[dict[str, Any]] = []
    meta_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for i, ep in enumerate(episodes_in, 1):
        row = _run_for_source(ingest["runs"], ep["source"])
        model, arm, run_id = parse_source(ep["source"])
        key = (model, arm)
        if key not in meta_cache:
            meta_cache[key] = load_meta(rerun, model, arm)
        rec = next((m for m in meta_cache[key] if m.get("run_id") == run_id), {})
        src = atof_path(extracted, model, arm, run_id)
        built.append(
            build_episode(
                episode_id=f"TP-2026-08-06-E{i:02d}",
                ep=ep,
                row=row,
                atof=src,
                tail=str(rec.get("tail") or ""),
            )
        )
    label_counts = Counter(lab for ep in built for lab in ep["detectors"])
    overlap = Counter(tuple(ep["detectors"]) for ep in built)
    models = Counter(ep["model"] for ep in built)
    tasks = Counter(ep["task"] for ep in built)
    return {
        "packet_version": PACKET_VERSION,
        "status": "WAITING_FOR_HUMAN_LABELS",
        "dataset": DATASET,
        "v0_4_sha": V0_4_SHA,
        "harness_sha": harness_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "REAL_ATOF_DATA": "available",
        "detector_hits": 19,
        "unique_episodes": 13,
        "overlaps_collapsed": sum(1 for ep in built if len(ep["detectors"]) > 1),
        "by_detector": dict(label_counts),
        "overlap_distribution": {"+".join(k): v for k, v in overlap.items()},
        "model_distribution": dict(models),
        "task_distribution": dict(tasks),
        "w1_fired": label_counts.get("W1", 0),
        "notes": [
            "Judge the episode, not the detector. A retry after error is not inherently waste.",
            "Do not treat extra turns as waste. Record candidate_relationship_to_outcome separately.",
            "HUMAN_VERDICT allowed: waste | not_waste | unsure. Do not pre-fill.",
            "Labels are annotations. TraceV1 is not modified.",
        ],
        "episodes": built,
    }


def merge_human_fields(packet: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    """Keep HUMAN_* annotations when regenerating context from traces."""
    if not existing:
        return packet
    old_by_id = {ep.get("episode_id"): ep for ep in (existing.get("episodes") or [])}
    for ep in packet["episodes"]:
        old = old_by_id.get(ep.get("episode_id"))
        if not old:
            continue
        for key in ("HUMAN_VERDICT", "HUMAN_REASON", "candidate_relationship_to_outcome"):
            if old.get(key) not in (None, ""):
                ep[key] = old[key]
    if labels_complete(packet):
        packet["status"] = "LABELS_PRESENT"
    return packet


def labels_complete(packet: dict[str, Any]) -> bool:
    episodes = packet.get("episodes") or []
    if len(episodes) != 13:
        return False
    return all(ep.get("HUMAN_VERDICT") in ALLOWED_VERDICTS for ep in episodes)


def score_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Compute detector validity. Recall and prevalence are unsupported."""
    if not labels_complete(packet):
        unlabeled = [
            ep.get("episode_id")
            for ep in (packet.get("episodes") or [])
            if ep.get("HUMAN_VERDICT") not in ALLOWED_VERDICTS
        ]
        return {
            "status": "WAITING_FOR_HUMAN_LABELS",
            "unlabeled_episode_ids": unlabeled,
            "precision": None,
            "taxonomy": None,
            "metrics": None,
        }
    episodes = packet["episodes"]
    decided = [ep for ep in episodes if ep["HUMAN_VERDICT"] in ("waste", "not_waste")]
    by_w: dict[str, dict[str, Any]] = {}
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        rows = [ep for ep in episodes if label in (ep.get("detectors") or [])]
        d = [ep for ep in rows if ep["HUMAN_VERDICT"] in ("waste", "not_waste")]
        waste_n = sum(1 for ep in d if ep["HUMAN_VERDICT"] == "waste")
        not_waste_n = sum(1 for ep in d if ep["HUMAN_VERDICT"] == "not_waste")
        unsure_n = sum(1 for ep in rows if ep["HUMAN_VERDICT"] == "unsure")
        by_w[label] = {
            "unique_episodes": len(rows),
            "decided": len(d),
            "waste": waste_n,
            "not_waste": not_waste_n,
            "unsure": unsure_n,
            "precision_among_decided": (waste_n / len(d)) if d else None,
        }
    combos: dict[str, dict[str, Any]] = {}
    for ep in episodes:
        key = "+".join(ep.get("detectors") or [])
        slot = combos.setdefault(
            key,
            {"unique_episodes": 0, "waste": 0, "not_waste": 0, "unsure": 0},
        )
        slot["unique_episodes"] += 1
        verd = ep["HUMAN_VERDICT"]
        if verd in slot:
            slot[verd] += 1
    taxonomy = _taxonomy_draft(by_w, combos)
    return {
        "status": "LABELED",
        "n_episodes": 13,
        "decided": len(decided),
        "waste": sum(1 for ep in decided if ep["HUMAN_VERDICT"] == "waste"),
        "not_waste": sum(1 for ep in decided if ep["HUMAN_VERDICT"] == "not_waste"),
        "unsure": sum(1 for ep in episodes if ep["HUMAN_VERDICT"] == "unsure"),
        "by_detector": by_w,
        "overlap_combinations": combos,
        "taxonomy": taxonomy,
        "recall": "unsupported",
        "population_prevalence": "unsupported",
        "composite_score": "forbidden",
        "metrics": None,
    }


def _taxonomy_draft(by_w: dict[str, dict[str, Any]], combos: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Draft KEEP/REFINE/MERGE/DROP from labeled precision. Humans can override."""
    recs: dict[str, dict[str, Any]] = {}
    for label, stats in by_w.items():
        n = stats["unique_episodes"]
        decided = stats["decided"]
        prec = stats["precision_among_decided"]
        if n == 0:
            recs[label] = {
                "action": "KEEP",
                "reason": "no hits on this 13-episode set; absence is not a drop decision",
            }
            continue
        if decided == 0:
            recs[label] = {
                "action": "KEEP",
                "reason": "hits exist but all labels are unsure; no precision yet",
            }
            continue
        if prec is None:
            recs[label] = {"action": "KEEP", "reason": "no decided labels"}
        elif prec >= 0.8:
            recs[label] = {"action": "KEEP", "reason": f"precision {prec:.2f} among {decided} decided"}
        elif prec <= 0.2:
            recs[label] = {"action": "REFINE", "reason": f"precision {prec:.2f} among {decided} decided"}
        else:
            recs[label] = {"action": "REFINE", "reason": f"mixed precision {prec:.2f} among {decided} decided"}
    w3w5 = combos.get("W3+W5") or {}
    if w3w5.get("unique_episodes") and by_w["W3"]["unique_episodes"] == w3w5.get("unique_episodes") and by_w["W5"]["unique_episodes"] == w3w5.get("unique_episodes"):
        recs["W3+W5"] = {
            "action": "MERGE",
            "reason": "every W3 hit in this packet is also W5; unique contribution is unproven here",
        }
    return recs


def render_packet_md(packet: dict[str, Any]) -> str:
    lines = [
        "# v0.4.1 — Real ATOF waste adjudication",
        "",
        f"Status: **{packet['status']}**",
        f"Dataset: `{packet['dataset']}`",
        f"v0.4 SHA: `{packet['v0_4_sha']}`",
        f"Harness SHA: `{packet.get('harness_sha')}`",
        "",
        "This is a detector-validity packet, not a prevalence estimate.",
        "Do **not** answer “how much of Hermes is wasted?”",
        "Judge the **episode**, not the detector. Extra turns are not automatically waste.",
        "",
        f"Detector hits: **{packet['detector_hits']}**",
        f"Unique episodes: **{packet['unique_episodes']}**",
        f"Overlaps collapsed: **{packet['overlaps_collapsed']}**",
        f"By detector: `{packet['by_detector']}`",
        f"Overlap distribution: `{packet['overlap_distribution']}`",
        f"Models: `{packet['model_distribution']}`",
        f"Tasks: `{packet['task_distribution']}`",
        f"W1 fired: **{packet['w1_fired']}** (retries after error usually changed arguments).",
        "",
        "Allowed `HUMAN_VERDICT`: `waste` | `not_waste` | `unsure`.",
        "Allowed `candidate_relationship_to_outcome`: `recovery` | `neutral` | `harmful` | `unknown`.",
        "Leave both empty until a human fills them. Do not self-label.",
        "",
        "Fill the JSON (`results/atof-waste-adjudication.json`) or this sheet, then return it.",
        "Precision / KEEP-REFINE-MERGE-DROP are computed only after labels exist.",
        "",
        "## Interesting ambiguities (not verdicts)",
        "",
        "- **E01–E06 (W3+W5, `err_multi_dir`):** three `read_file` calls on `pkg_a` / `pkg_b` / `pkg_c` with different contents. Ingest pairing dropped arguments, so the detector saw identical null-arg retries. Decide whether this is wasted reread or parallel distinct reads. Task outcome is `unknown` (filesystem oracle).",
        "- **E07–E13 (W6):** zero structured tools and raw `<function=...>` in the tail. Decide waste vs provider/template failure. All seven are tail-oracle **failure** and look abandoned after one LLM turn.",
        "- **E09 / E11** are `err_inline_script`; the others in this W6 set are `err_big_output`. Same detector, two induced traps.",
        "",
        "## Episodes",
        "",
    ]
    for ep in packet["episodes"]:
        lines.extend(
            [
                f"### {ep['episode_id']}",
                "",
                f"- model `{ep['model']}` arm `{ep['arm']}` task `{ep['task']}` rep `{ep.get('rep')}` run `{ep['run_id']}`",
                f"- Hermes SHA `{ep['hermes_sha']}`",
                f"- detectors: `{','.join(ep['detectors'])}` tool `{ep.get('tool_name')}`",
                f"- args_changed `{ep.get('args_changed')}` state_changed `{ep.get('state_changed')}` error_occurred `{ep.get('error_occurred')}`",
                f"- task_outcome **{ep['task_outcome']}** (`{ep.get('task_outcome_note')}`)",
                f"- candidate_relationship_to_outcome: _{ep.get('candidate_relationship_to_outcome')}_",
                f"- turns_remaining_after_candidate `{ep.get('turns_remaining_after_candidate')}`",
                f"- previous: `{_snip(ep.get('previous_action'))}` → `{ep.get('previous_result_summary')}`",
                f"- current: `{_snip(ep.get('current_action'))}` → `{ep.get('current_result_summary')}`",
                "- trajectory (1–2 before / candidate / 1–2 after):",
                f"  - before: `{_snip(ep['trajectory']['before'])}`",
                f"  - candidate: `{_snip(ep['trajectory']['candidate'])}`",
                f"  - after: `{_snip(ep['trajectory']['after'])}`",
                f"- detector evidence: `{ep.get('detector_evidence')}`",
                f"- tail: `{ep.get('final_output_tail')}`",
                "- HUMAN_VERDICT:",
                "- HUMAN_REASON:",
                "",
            ]
        )
    lines.extend(
        [
            "## Next gate",
            "",
            "**WAITING_FOR_HUMAN_LABELS**",
            "",
            "After labels: `python -m hermes_eval score-adjudication`.",
            "That pass computes detector precision among decided episodes, overlap",
            "combinations, unique contribution, and a *draft* KEEP / REFINE / MERGE / DROP table.",
            "Draft taxonomy is heuristic; humans can override. It will not compute recall or",
            "population prevalence, and will not emit a composite waste score.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def default_ingest_path() -> Path:
    return REPO_ROOT / "results" / "toolperf-ingest.json"


def default_json_path() -> Path:
    return REPO_ROOT / "results" / "atof-waste-adjudication.json"


def default_md_path() -> Path:
    return REPO_ROOT / "reports" / "evals" / "atof-waste-adjudication.md"
