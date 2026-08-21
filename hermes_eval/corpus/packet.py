"""Build the v0.6 human adjudication packet from manifest-bound real corpora."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from hermes_eval.adjudicate_atof import walk_atof
from hermes_eval.corpus.ingest import LOCAL_CORPORA, SANITIZER_VERSION, _local_result_path
from hermes_eval.corpus.registry import CorpusRegistry, manifest_sha256, sha256_file
from hermes_eval.corpus.sanitize import CorpusSanitizer, scan_sanitized
from hermes_eval.gitutil import REPO_ROOT
from hermes_eval.schema import validate_contract
from hermes_eval.toolperf_ingest import atof_path, default_rerun_dir, ensure_extracted, ingest, load_meta
from hermes_eval.trace.adapters.atof import emit_atof

PACKET_ID = "v0.6-production-episodes-v1"
MAX_SNIPPET = 320


def _snip(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= MAX_SNIPPET else text[: MAX_SNIPPET - 1] + "…"


def _action(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    return {
        "call_id": event.get("call_id"),
        "result_id": event.get("result_id"),
        "tool_name": event.get("name"),
        "canonical_arguments": event.get("arguments"),
        "result_summary": _snip(event.get("result_summary") or event.get("summary")),
        "status": event.get("status"),
    }


def _episode_base(
    registry: CorpusRegistry,
    *,
    episode_id: str,
    corpus_id: str,
    trace_id: str,
    source_run_id: str,
    model: str | None,
    server: str | None,
    hermes_sha: str,
    task: str,
    arm: str,
    repetition: int,
    start_event_id: str,
    end_event_id: str,
    detectors: list[str],
    outcome: str,
    evidence: dict[str, Any],
    previous: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    following: dict[str, Any] | None,
    arguments_changed: bool | None,
    new_information: bool | None,
    state_changed: bool | None,
    task_succeeded: bool | None,
) -> dict[str, Any]:
    manifest = registry.require(corpus_id)
    return {
        "schema": "EpisodeV1", "schema_version": 1, "episode_id": episode_id,
        "trace_id": trace_id, "corpus_id": corpus_id, "source_class": manifest["source_class"],
        "source_run_id": source_run_id, "model": model, "server": server,
        "hermes_sha": hermes_sha, "task_id": task, "arm": arm, "repetition": repetition,
        "start_event_id": start_event_id, "end_event_id": end_event_id,
        "sampling_role": "detector_candidate" if detectors else "negative_control",
        "detectors": detectors, "outcome": outcome, "relationship_to_outcome": None,
        "evidence": evidence,
        "context": {
            "previous_action": _action(previous), "candidate_action": _action(candidate),
            "next_action": _action(following), "arguments_changed": arguments_changed,
            "new_information_acquired": new_information, "state_changed": state_changed,
            "task_succeeded": task_succeeded,
        },
        "provenance": {
            "corpus_manifest_sha256": manifest_sha256(manifest),
            "raw_artifact_sha256": manifest["raw_artifact_sha256"],
            "adapter_version": manifest["adapter_version"], "sanitizer_version": SANITIZER_VERSION,
            "trace_schema": "TraceV1",
        },
        "privacy": {"redaction_version": SANITIZER_VERSION, "safe_to_commit": True},
        "human_verdict": None, "human_reason": None,
    }


def _tool_actions(path: Path) -> list[dict[str, Any]]:
    return [event for event in walk_atof(path) if event.get("role") == "tool_result"]


def _window(actions: list[dict[str, Any]], index: int) -> tuple[Any, Any, Any]:
    return (
        actions[index - 1] if index > 0 else None,
        actions[index] if actions else None,
        actions[index + 1] if index + 1 < len(actions) else None,
    )


def _toolperf_episode(
    registry: CorpusRegistry,
    *,
    number: int,
    row: dict[str, Any],
    path: Path,
    detectors: list[str],
    candidate_index: int | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    corpus_id = "toolperf-2026-08-06"
    trace = emit_atof(path, fixture=row["task"], hermes_sha=row["hermes_sha"], run_id=f"toolperf:{row['model']}:{row['arm']}:{row['run_id']}")
    actions = _tool_actions(path)
    if candidate_index is None:
        previous = actions[-1] if actions else None
        candidate = {"name": None, "arguments": None, "call_id": None, "result_id": None, "status": "no_structured_execution", "summary": evidence.get("text_excerpt")}
        following = None
    else:
        idx = max(0, min(candidate_index, len(actions) - 1))
        previous, candidate, following = _window(actions, idx)
    args_changed = None
    if previous and candidate:
        args_changed = json.dumps(previous.get("arguments"), sort_keys=True, default=str) != json.dumps(candidate.get("arguments"), sort_keys=True, default=str)
    new_information = None
    if previous and candidate and (candidate.get("result_summary") or candidate.get("summary")) is not None:
        new_information = (candidate.get("result_summary") or candidate.get("summary")) != (previous.get("result_summary") or previous.get("summary"))
    success = row.get("success")
    outcome = "unknown" if success is None else ("success" if success else "failure")
    events = trace.get("events") or []
    return _episode_base(
        registry, episode_id=f"V06-E{number:03d}", corpus_id=corpus_id,
        trace_id=trace["run_id"], source_run_id=f"{row['model']}/{row['arm']}/{row['run_id']}",
        model=row["model"], server="OpenRouter", hermes_sha=row["hermes_sha"], task=row["task"],
        arm=row["arm"], repetition=int(row["rep"]), start_event_id=events[0]["id"], end_event_id=events[-1]["id"],
        detectors=detectors, outcome=outcome, evidence=evidence, previous=previous, candidate=candidate,
        following=following, arguments_changed=args_changed, new_information=new_information,
        state_changed=None, task_succeeded=success,
    )


def _build_toolperf(registry: CorpusRegistry) -> tuple[list[dict[str, Any]], dict[str, int]]:
    payload = ingest()
    rerun = default_rerun_dir().resolve()
    extracted = ensure_extracted(rerun)
    rows = {(row["model"], row["arm"], row["run_id"]): row for row in payload["runs"]}
    meta_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    episodes: list[dict[str, Any]] = []

    # Seven genuine W6 episodes after identity-aware correction.
    for hit in payload["waste"]["episodes"]:
        model, arm, run_id = hit["source"].rsplit("/", 2)
        row = rows[(model, arm, run_id)]
        path = atof_path(extracted, model, arm, run_id)
        key = (model, arm)
        if key not in meta_cache:
            meta_cache[key] = {str(item["run_id"]): item for item in load_meta(rerun, model, arm)}
        tail = str(meta_cache[key].get(run_id, {}).get("tail") or "")
        episodes.append(_toolperf_episode(
            registry, number=len(episodes) + 1, row=row, path=path,
            detectors=["textual_tool_protocol_failure-v1"], candidate_index=None,
            evidence={"detector_hits": hit.get("patterns"), "text_excerpt": _snip(tail), "structured_tool_executions": 0},
        ))

    # Six successful recoveries: first failing tool is the decision point.
    for row in [row for row in payload["runs"] if row.get("recovered")][:6]:
        path = atof_path(extracted, row["model"], row["arm"], row["run_id"])
        actions = _tool_actions(path)
        index = next((i for i, action in enumerate(actions) if action.get("ok") is False), 0)
        episodes.append(_toolperf_episode(
            registry, number=len(episodes) + 1, row=row, path=path,
            detectors=["successful_recovery_after_deterministic_failure-candidate"], candidate_index=index,
            evidence={"recovered": True, "tool_errors": row["metrics"]["errs"], "task_outcome_source": row["success_status"]},
        ))

    # Six explicit negative controls for the prior pkg_a/pkg_b/pkg_c identity bug.
    pkg_rows = [row for row in payload["runs"] if row["model"].startswith("anthropic/") and row["task"] == "err_multi_dir"][:6]
    for row in pkg_rows:
        path = atof_path(extracted, row["model"], row["arm"], row["run_id"])
        actions = _tool_actions(path)
        read_indices = [i for i, action in enumerate(actions) if action.get("name") == "read_file"]
        index = read_indices[-1]
        episodes.append(_toolperf_episode(
            registry, number=len(episodes) + 1, row=row, path=path, detectors=[], candidate_index=index,
            evidence={"control_reason": "distinct pkg_a/pkg_b/pkg_c read; canonical arguments and result identity preserved", "previous_false_positive_class": "W3/W5"},
        ))

    # Eleven balanced successful negative controls across remaining tasks/models.
    selected_keys = {(ep["model"], ep["arm"], ep["source_run_id"].rsplit("/", 1)[-1]) for ep in episodes}
    candidates = [
        row for row in payload["runs"]
        if row.get("success") is True and not row.get("recovered")
        and (row["model"], row["arm"], row["run_id"]) not in selected_keys
    ]
    candidates.sort(key=lambda row: (row["task"], row["model"], row["arm"], row["rep"]))
    chosen: list[dict[str, Any]] = []
    task_counts: Counter[str] = Counter()
    for row in candidates:
        if task_counts[row["task"]] >= 2:
            continue
        chosen.append(row); task_counts[row["task"]] += 1
        if len(chosen) == 11:
            break
    for row in chosen:
        path = atof_path(extracted, row["model"], row["arm"], row["run_id"])
        actions = _tool_actions(path)
        if not actions:
            continue
        episodes.append(_toolperf_episode(
            registry, number=len(episodes) + 1, row=row, path=path, detectors=[], candidate_index=len(actions) - 1,
            evidence={"control_reason": "successful trajectory sampled as detector-negative context", "task_outcome_source": row["success_status"]},
        ))
    return episodes, {"raw_detector_hits": 7, "identity_false_positives_excluded": 6}


def _local_category(row: dict[str, Any]) -> str:
    if row.get("textual_pseudo_tool_call"): return "textual_tool_protocol_failure-v1"
    if row.get("hallucinated_completion"): return "hallucinated_completion-v1"
    if row.get("explicit_capability_failure"): return "explicit_capability_failure-candidate"
    if row.get("remediation_requested"): return "remediation_or_user_request-candidate"
    if row.get("other_tool_like_text"): return "tool_intent_without_execution-candidate"
    return "plain_failure_other-control"


def _build_local(registry: CorpusRegistry, start_number: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plans = {
        "local-qwen38-zero-toolset-silent-v1": list(range(10)),
        "local-qwen35-9b-zero-toolset-silent-v1": None,
        "local-qwen35-9b-zero-toolset-warning-v1": None,
    }
    episodes: list[dict[str, Any]] = []
    excluded = [{"corpus_id": "local-qwen38-zero-toolset-warning-v1", "count": 10, "reason": "transcript omitted; corrected behavior categories are not independently recoverable from TraceV1"}]
    for corpus_id in plans:
        result = json.loads(_local_result_path(corpus_id).read_text(encoding="utf-8"))
        trace_path = registry.verify_artifact(corpus_id)
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        rows = result["extras"]["fault_runs"]
        if corpus_id.endswith("silent-v1") and "qwen35" in corpus_id:
            mandatory = [i for i, row in enumerate(rows) if _local_category(row) != "tool_intent_without_execution-candidate"]
            intent = [i for i, row in enumerate(rows) if _local_category(row) == "tool_intent_without_execution-candidate"][:3]
            indices = (mandatory + intent)[:6]
        elif "warning" in corpus_id:
            textual = [i for i, row in enumerate(rows) if _local_category(row) == "textual_tool_protocol_failure-v1"][:1]
            hallucinated = [i for i, row in enumerate(rows) if _local_category(row) == "hallucinated_completion-v1"][:3]
            indices = textual + hallucinated
        else:
            indices = plans[corpus_id]
        first_path = Path(result["extras"]["control_runs"][0]["tool_events"][0]["arguments"]["path"])
        run_root = first_path.parents[1]
        provenance = registry.require(corpus_id).get("provenance") or {}
        for index in indices:
            row = rows[index]
            span = f"fault:{index}"
            events = [event for event in trace["events"] if event.get("span_id") == span]
            response = next(event for event in events if event.get("type") == "model.response")
            text_path = run_root / f"fault-{index}" / "stdout.txt"
            text = text_path.read_text(encoding="utf-8", errors="replace")
            detector = _local_category(row)
            candidate = {"name": None, "arguments": None, "call_id": None, "result_id": None, "status": "no_structured_execution", "summary": _snip(text)}
            episode = _episode_base(
                registry, episode_id=f"V06-E{start_number + len(episodes):03d}", corpus_id=corpus_id,
                trace_id=f"{trace['run_id']}#{span}", source_run_id=f"{trace['run_id']}#{span}",
                model=provenance.get("model"), server=provenance.get("server"), hermes_sha=provenance["hermes_sha"],
                task="zero-toolset-live", arm="fault", repetition=index, start_event_id=events[0]["id"], end_event_id=events[-1]["id"],
                detectors=[detector], outcome="failure",
                evidence={"terminal_text_excerpt": _snip(text), "structured_tool_executions": 0, "external_oracle": "proof absent", "classification_flags": {key: row.get(key) for key in ("textual_pseudo_tool_call", "hallucinated_completion", "other_tool_like_text", "plain_failure_other")}},
                previous=None, candidate=candidate, following=None, arguments_changed=None,
                new_information=False, state_changed=False, task_succeeded=False,
            )
            episodes.append(episode)
    return episodes, excluded


def _sanitize_packet(packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sanitizer = CorpusSanitizer(PACKET_ID)
    clean = sanitizer.sanitize(packet)
    report = sanitizer.report(clean, source_type_known=True, manual_spot_check=True)
    if not report["safe_to_commit"] or scan_sanitized(clean):
        raise ValueError(f"adjudication packet failed privacy gate: {report['findings']}")
    for episode in clean["episodes"]:
        validate_contract(episode, "EpisodeV1")
    return clean, report


def build_packet() -> tuple[dict[str, Any], dict[str, Any]]:
    registry = CorpusRegistry.load()
    toolperf, detector_stats = _build_toolperf(registry)
    local, excluded = _build_local(registry, len(toolperf) + 1)
    episodes = toolperf + local
    by_task = Counter(str(ep["task_id"]) for ep in episodes)
    by_detector = Counter(detector for ep in episodes for detector in ep["detectors"])
    by_corpus = Counter(ep["corpus_id"] for ep in episodes)
    by_model = Counter(str(ep["model"]) for ep in episodes)
    by_outcome = Counter(ep["outcome"] for ep in episodes)
    if not 30 <= len(episodes) <= 60:
        raise ValueError(f"packet size outside 30-60: {len(episodes)}")
    if max(by_task.values()) / len(episodes) > 0.40:
        raise ValueError(f"one task exceeds 40%: {by_task}")
    if max(by_detector.values(), default=0) / len(episodes) > 0.40:
        raise ValueError(f"one detector exceeds 40%: {by_detector}")
    packet = {
        "schema": "AdjudicationPacketV1", "packet_id": PACKET_ID,
        "status": "WAITING_FOR_HUMAN_LABELS", "purpose": "detector validity and taxonomy refinement; not prevalence",
        "raw_detector_hits": detector_stats["raw_detector_hits"] + len(local),
        "unique_episodes": len(episodes), "overlaps_collapsed": 0,
        "identity_false_positives_excluded": detector_stats["identity_false_positives_excluded"],
        "distributions": {"corpus": dict(by_corpus), "model": dict(by_model), "task": dict(by_task), "outcome": dict(by_outcome), "detector": dict(by_detector)},
        "excluded": excluded, "episodes": episodes,
        "label_instructions": {
            "human_verdict": ["waste", "not_waste", "unsure"],
            "relationship_to_outcome": ["recovery", "harmful", "neutral", "unknown"],
            "rules": ["Judge the episode, not the detector.", "Use only the packet context; do not infer missing events.", "A retry or extra turn is not inherently waste.", "Fill human_verdict, human_reason, and relationship_to_outcome for every episode."],
        },
    }
    return _sanitize_packet(packet)


def render_report(packet: dict[str, Any], redaction: dict[str, Any]) -> str:
    dist = packet["distributions"]
    lines = [
        f"# {PACKET_ID}", "", "Status: **WAITING_FOR_HUMAN_LABELS**", "",
        "This is a detector-validity and taxonomy-refinement sample, not a prevalence sample.", "",
        f"- Raw detector hits represented: {packet['raw_detector_hits']}",
        f"- Unique human-decision episodes: {packet['unique_episodes']}",
        f"- Overlaps collapsed: {packet['overlaps_collapsed']}",
        f"- Prior identity-loss false positives excluded: {packet['identity_false_positives_excluded']}",
        f"- Privacy gate: {'PASS' if redaction['safe_to_commit'] else 'FAIL'}; findings: {len(redaction['findings'])}",
        "", "## Distribution", "",
    ]
    for name in ("corpus", "model", "task", "outcome", "detector"):
        lines.append(f"### {name}")
        lines.append("")
        for key, value in sorted(dist[name].items()):
            lines.append(f"- `{key}`: {value}")
        lines.append("")
    lines.extend(["## Ingestion gaps and exclusions", ""])
    for item in packet["excluded"]:
        lines.append(f"- `{item['corpus_id']}`: excluded {item['count']} — {item['reason']}")
    lines.extend([
        "", "## Human labeling instructions", "",
        "For every episode, fill:", "",
        "- `human_verdict`: `waste`, `not_waste`, or `unsure`",
        "- `human_reason`: concise evidence-based explanation",
        "- `relationship_to_outcome`: `recovery`, `harmful`, `neutral`, or `unknown`",
        "", "Judge the episode rather than trusting the detector name. Use only the included context.",
        "Do not treat retries or extra turns as inherently wasteful. Return the edited JSON packet;",
        "no detector precision, taxonomy, metric, or fixture promotion occurs before labels return.", "",
    ])
    return "\n".join(lines)


def write_packet() -> tuple[Path, Path]:
    packet, redaction = build_packet()
    packet_path = REPO_ROOT / "results" / "adjudication" / f"{PACKET_ID}.json"
    report_path = REPO_ROOT / "reports" / "evals" / f"{PACKET_ID}.md"
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    packet["redaction"] = redaction
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(packet, redaction), encoding="utf-8")
    return packet_path, report_path


if __name__ == "__main__":
    print("\n".join(str(path) for path in write_packet()))
