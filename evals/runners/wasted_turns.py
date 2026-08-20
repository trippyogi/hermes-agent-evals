"""Conservative wasted-turn candidate parser.

Does not claim every detection is objectively waste. Emits evidence for
human labeling. Never reads ~/.hermes or the user's real session DB.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

TEXT_TOOL_RE = re.compile(
    r'(\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:)|(<function=\w+>)',
    re.DOTALL,
)

W_LABELS = {
    "repeat_identical_tool_after_failure": "W1",
    "tool_against_dead_runtime": "W2",
    "retry_no_state_change": "W3",
    "tool_immediately_undone": "W4",
    "repeated_identical_read": "W5",
    "empty_schema_then_textual_pseudo_call": "W6",
    "textual_pseudo_tool_call": "W6",
}


def _norm_args(args: Any) -> str:
    if isinstance(args, dict):
        return json.dumps(args, sort_keys=True, default=str)
    return str(args or "")


def _hash(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _iter_events(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        if isinstance(payload.get("events"), list):
            return [e for e in payload["events"] if isinstance(e, dict)]
        if isinstance(payload.get("messages"), list):
            events = []
            for msg in payload["messages"]:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role == "tool" or msg.get("type") == "tool":
                    events.append(
                        {
                            "type": "tool",
                            "name": msg.get("name") or msg.get("tool_name"),
                            "arguments": msg.get("arguments") or msg.get("args"),
                            "status": msg.get("status") or ("error" if msg.get("error") else "ok"),
                            "content": msg.get("content") or msg.get("result"),
                        }
                    )
                elif role == "assistant":
                    events.append({"type": "assistant", "content": msg.get("content")})
            return events
        if isinstance(payload.get("atof"), dict) and isinstance(payload.get("events"), list):
            return [e for e in payload["events"] if isinstance(e, dict)]
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    return []


def _candidate(
    *,
    pattern: str,
    index: int | None,
    source: str,
    evidence: str,
    confidence: str,
    tool: str | None = None,
    previous_result_hash: str | None = None,
    state_changed: bool | None = None,
    extra: dict | None = None,
) -> dict:
    payload = {
        "w_label": W_LABELS.get(pattern, "W?"),
        "pattern": pattern,
        "confidence": confidence,
        "index": index,
        "tool": tool,
        "evidence": evidence,
        "state_changed": state_changed,
        "previous_result_hash": previous_result_hash,
        "source": source,
        "human_verdict": None,
        "human_notes": None,
        "label": "unlabeled",
    }
    if extra:
        payload.update(extra)
    return payload


def detect_candidates(payload: Any, source: str) -> list[dict]:
    events = _iter_events(payload)
    candidates: list[dict] = []
    prev_tool = None
    prev_failed = False
    prev_state_token = None
    prev_result_hash = None
    prev_name = None

    for idx, ev in enumerate(events):
        if ev.get("type") != "tool":
            content = str(ev.get("content") or ev.get("transcript") or "")
            if TEXT_TOOL_RE.search(content):
                candidates.append(
                    _candidate(
                        pattern="textual_pseudo_tool_call",
                        index=idx,
                        source=source,
                        evidence="assistant text matches a tool-call shape and no structured tool event in this slice",
                        confidence="medium",
                        state_changed=False,
                    )
                )
            continue

        name = ev.get("name") or ev.get("tool")
        args = _norm_args(ev.get("arguments") or ev.get("args"))
        status = str(ev.get("status") or "").lower()
        failed = status in {"error", "failed", "err"} or bool(ev.get("error"))
        state_token = ev.get("cwd") or ev.get("session_id") or ev.get("runtime_id")
        result_hash = _hash(ev.get("content") or ev.get("result") or status)
        state_changed = prev_state_token is not None and prev_state_token != state_token

        if prev_tool == (name, args) and prev_failed and failed:
            candidates.append(
                _candidate(
                    pattern="repeat_identical_tool_after_failure",
                    index=idx,
                    source=source,
                    evidence="same name+args after a deterministic-looking failure, no recorded intervening state change",
                    confidence="medium",
                    tool=str(name),
                    previous_result_hash=prev_result_hash,
                    state_changed=state_changed,
                )
            )
        if prev_tool == (name, args) and not state_changed and prev_name == name:
            candidates.append(
                _candidate(
                    pattern="retry_no_state_change",
                    index=idx,
                    source=source,
                    evidence="identical retry with unchanged state token",
                    confidence="low",
                    tool=str(name),
                    previous_result_hash=prev_result_hash,
                    state_changed=False,
                )
            )
        if prev_tool == (name, args) and not failed and name in {"read_file", "read", "cat"}:
            candidates.append(
                _candidate(
                    pattern="repeated_identical_read",
                    index=idx,
                    source=source,
                    evidence="identical read with unchanged arguments",
                    confidence="low",
                    tool=str(name),
                    previous_result_hash=prev_result_hash,
                    state_changed=state_changed,
                )
            )
        if ev.get("dead_runtime") or ev.get("session_dead"):
            candidates.append(
                _candidate(
                    pattern="tool_against_dead_runtime",
                    index=idx,
                    source=source,
                    evidence="event marked dead_runtime/session_dead",
                    confidence="high",
                    tool=str(name),
                    state_changed=False,
                )
            )
        undone = ev.get("undone_by") == idx + 1 or ev.get("immediately_undone")
        if not undone and idx + 1 < len(events):
            nxt = events[idx + 1]
            if nxt.get("type") == "tool":
                nname = nxt.get("name") or nxt.get("tool")
                if {name, nname} <= {"write_file", "delete_file", "patch"} or (
                    name == "pin" and nname == "unpin"
                ):
                    undone = True
        if undone:
            candidates.append(
                _candidate(
                    pattern="tool_immediately_undone",
                    index=idx,
                    source=source,
                    evidence="tool result immediately inverted by the next tool",
                    confidence="medium",
                    tool=str(name),
                    state_changed=True,
                )
            )

        prev_tool = (name, args)
        prev_failed = failed
        prev_state_token = state_token
        prev_result_hash = result_hash
        prev_name = name

    transcript = ""
    if isinstance(payload, dict):
        transcript = str(payload.get("transcript") or "")
    if transcript and TEXT_TOOL_RE.search(transcript):
        tool_events = [e for e in events if e.get("type") == "tool"]
        if not tool_events:
            candidates.append(
                _candidate(
                    pattern="empty_schema_then_textual_pseudo_call",
                    index=None,
                    source=source,
                    evidence="transcript contains a JSON/XML tool call and events have zero structured tools",
                    confidence="high",
                    state_changed=False,
                )
            )
    return candidates


def resolve_atof(scan_path: Path | None = None) -> tuple[str, str | None]:
    """REAL_ATOF_DATA is available only from HERMES_EVAL_ATOF_DIR or an ATOF jsonl.

    Never reads ~/.hermes. Scrubbed reconstruction is not ATOF.
    """
    env = (os.environ.get("HERMES_EVAL_ATOF_DIR") or "").strip()
    if env:
        path = Path(env)
        if path.is_dir() or path.is_file():
            return "available", str(path)
        return "BLOCKED", f"HERMES_EVAL_ATOF_DIR set but missing: {path}"
    if scan_path is not None:
        name = scan_path.name.lower()
        if "atof" in name and scan_path.exists():
            return "available", str(scan_path)
    return "BLOCKED", "HERMES_EVAL_ATOF_DIR unset; no ATOF jsonl provided"


def collapse_episodes(candidates: list[dict]) -> list[dict]:
    """Collapse detector hits that share (source, event index, tool).

    W1+W3 on the same retry is one human decision, not two independent rows.
    """
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for hit in candidates:
        key = (hit.get("source"), hit.get("index"), hit.get("tool"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(hit)
    episodes = []
    for key in order:
        hits = groups[key]
        labels = []
        for hit in hits:
            label = hit.get("w_label")
            if label and label not in labels:
                labels.append(label)
        patterns = []
        for hit in hits:
            pattern = hit.get("pattern")
            if pattern and pattern not in patterns:
                patterns.append(pattern)
        first = hits[0]
        episodes.append(
            {
                "source": first.get("source"),
                "index": first.get("index"),
                "tool": first.get("tool"),
                "w_labels": labels,
                "patterns": patterns,
                "hit_count": len(hits),
                "confidence": first.get("confidence"),
                "state_changed": first.get("state_changed"),
                "evidence": first.get("evidence"),
                "previous_result_hash": first.get("previous_result_hash"),
                "human_verdict": None,
                "human_notes": None,
                "label": "unlabeled",
            }
        )
    return episodes


def scan_path(path: Path) -> dict:
    candidates: list[dict] = []
    files = 0
    if path.is_file():
        targets = [path]
    else:
        targets = list(path.rglob("*.json")) + list(path.rglob("*.jsonl"))
    atof_status, atof_note = resolve_atof(path)
    if atof_status == "available" and atof_note:
        extra = Path(atof_note)
        if extra.is_file() and extra not in targets:
            targets.append(extra)
        elif extra.is_dir():
            for found in list(extra.rglob("*.json")) + list(extra.rglob("*.jsonl")):
                if found not in targets:
                    targets.append(found)
    for file in targets:
        files += 1
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            continue
        if file.suffix == ".jsonl":
            for line_no, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                candidates.extend(detect_candidates(payload, f"{file}:{line_no}"))
        else:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            candidates.extend(detect_candidates(payload, str(file)))
    episodes = collapse_episodes(candidates)
    counts = Counter(c["w_label"] for c in candidates)
    episode_label_counts = Counter(label for ep in episodes for label in ep.get("w_labels") or [])
    overlaps = sum(1 for ep in episodes if len(ep.get("w_labels") or []) > 1)
    return {
        "files_scanned": files,
        "detector_hits": len(candidates),
        "candidate_count": len(candidates),
        "episode_count": len(episodes),
        "overlaps_collapsed": overlaps,
        "by_w_label": dict(counts),
        "by_w_label_episodes": dict(episode_label_counts),
        "REAL_ATOF_DATA": atof_status,
        "REAL_ATOF_DATA_note": atof_note,
        "corpus": (
            "atof" if atof_status == "available" else "scrubbed_reconstruction"
        ),
        "candidates": candidates,
        "episodes": episodes,
        "note": (
            "Detector hits are not independent labels. Human labeling is on "
            "episodes (shared source, event index, tool). Do not auto-score. "
            f"REAL_ATOF_DATA={atof_status}."
        ),
    }


def render_label_sheet(scan: dict) -> str:
    lines = [
        "# Wasted-turn labeling sample (episodes)",
        "",
        "Do **not** train an automatic score from this sheet.",
        "Label **episodes**, not raw detector hits. W1+W3 on the same retry is one decision.",
        "Fill `HUMAN_VERDICT` with waste / not-waste / unsure.",
        "",
        f"REAL_ATOF_DATA: {scan.get('REAL_ATOF_DATA')}",
        f"Corpus: {scan.get('corpus')}",
        f"Detector hits: {scan.get('detector_hits')}",
        f"Unique episodes: {scan.get('episode_count')}",
        f"Overlaps collapsed: {scan.get('overlaps_collapsed')}",
        f"Hit labels: {scan.get('by_w_label')}",
        "",
        "| # | w_labels | tool | source | index | hits | state_changed | evidence | HUMAN_VERDICT |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, ep in enumerate(scan.get("episodes") or [], 1):
        evidence = str(ep.get("evidence") or "").replace("|", "/")
        source = str(ep.get("source") or "").replace("|", "/")
        labels = ",".join(ep.get("w_labels") or [])
        lines.append(
            f"| {i} | {labels} | `{ep.get('tool') or ''}` | `{source}` | "
            f"{ep.get('index')} | {ep.get('hit_count')} | {ep.get('state_changed')} | "
            f"{evidence} | |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--label-sheet", action="store_true")
    args = p.parse_args(argv)
    result = scan_path(args.path)
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        if args.label_sheet:
            md = args.out.with_suffix(".md")
            md.write_text(render_label_sheet(result), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
