"""Manifest-bound observational ingestion of the frozen v0.6 source corpora."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from hermes_eval.corpus.binding import attach_binding, build_binding, validate_trace_binding
from hermes_eval.corpus.registry import CorpusRegistry, manifest_sha256, sha256_file
from hermes_eval.corpus.sanitize import CorpusSanitizer, scan_sanitized
from hermes_eval.gitutil import REPO_ROOT
from hermes_eval.toolperf_ingest import (
    HERMES_SHA,
    atof_path,
    default_rerun_dir,
    ensure_extracted,
    ingest as ingest_toolperf,
)
from hermes_eval.trace.adapters.atof import emit_atof
from hermes_eval.trace.model import validate_trace

SANITIZER_VERSION = 1
LOCAL_CORPORA = (
    "local-qwen38-zero-toolset-silent-v1",
    "local-qwen38-zero-toolset-warning-v1",
    "local-qwen35-9b-zero-toolset-silent-v1",
    "local-qwen35-9b-zero-toolset-warning-v1",
)


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _span_trace(trace: dict[str, Any], span_id: str) -> dict[str, Any]:
    out = copy.deepcopy(trace)
    out["run_id"] = f"{trace['run_id']}#{span_id}"
    out["events"] = [event for event in trace.get("events", []) if event.get("span_id") == span_id]
    out["initial_state"] = {"source_trace": trace["run_id"], "span_id": span_id}
    out["final_state"] = {}
    out["metrics"] = {}
    out["artifacts"] = {"paths": [], "hashes": {}}
    return out


def _sanitize_bound_trace(trace: dict[str, Any], corpus_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sanitizer = CorpusSanitizer(corpus_id)
    clean = sanitizer.sanitize(trace)
    report = sanitizer.report(clean, source_type_known=True, manual_spot_check=True)
    if not report["safe_to_commit"]:
        raise ValueError(f"sanitized trace failed closed for {corpus_id}: {report['findings']}")
    if scan_sanitized(clean):
        raise ValueError(f"residual sensitive data in {corpus_id}")
    return clean, report


def _write_corpus(
    out_root: Path,
    manifest: dict[str, Any],
    traces: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    dest = out_root / manifest["corpus_id"]
    _dump(dest / "manifest.json", manifest)
    _dump(dest / "bindings.json", {"schema": "CorpusBindingsV1", "bindings": bindings})
    traces_path = dest / "traces.jsonl"
    traces_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in traces), encoding="utf-8")
    combined = {
        "redaction_version": SANITIZER_VERSION,
        "corpus_id": manifest["corpus_id"],
        "trace_count": len(traces),
        "safe_to_commit": all(row.get("safe_to_commit") for row in reports),
        "findings": [finding for row in reports for finding in row.get("findings", [])],
        "source_reports": reports,
    }
    if not combined["safe_to_commit"] or combined["findings"]:
        raise ValueError(f"corpus derivative is not safe to commit: {manifest['corpus_id']}")
    _dump(dest / "redaction.json", combined)
    return {
        "corpus_id": manifest["corpus_id"],
        "manifest_sha256": manifest_sha256(manifest),
        "trace_count": len(traces),
        "binding_count": len(bindings),
        "traces_sha256": sha256_file(traces_path),
        "safe_to_commit": True,
    }


def ingest_toolperf_corpus(registry: CorpusRegistry, out_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    corpus_id = "toolperf-2026-08-06"
    artifact = registry.verify_artifact(corpus_id)
    rerun = default_rerun_dir().resolve()
    extracted = ensure_extracted(rerun)
    payload = ingest_toolperf(rerun)
    frozen = _json(REPO_ROOT / "results" / "v0.5-final-toolperf.json")
    frozen_ids = sorted((row["model"], row["arm"], row["run_id"]) for row in frozen["runs"])
    current_ids = sorted((row["model"], row["arm"], row["run_id"]) for row in payload["runs"])
    if payload["gate1_metric_matches"] != 108 or payload["mismatches"] or current_ids != frozen_ids:
        raise ValueError("toolperf observational equivalence gate failed")
    frozen_sha = {(row["model"], row["arm"], row["run_id"]): row["atof_sha256"] for row in frozen["runs"]}

    traces: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for row in payload["runs"]:
        key = (row["model"], row["arm"], row["run_id"])
        if row["atof_sha256"] != frozen_sha[key]:
            raise ValueError(f"toolperf source checksum drift: {key}")
        src = atof_path(extracted, row["model"], row["arm"], row["run_id"])
        trace = emit_atof(src, fixture=row["task"], hermes_sha=row["hermes_sha"], run_id=f"toolperf:{row['model']}:{row['arm']}:{row['run_id']}")
        binding = build_binding(
            registry, corpus_id=corpus_id, source_run_identity=f"{row['model']}/{row['arm']}/{row['run_id']}",
            model=row["model"], hermes_sha=row["hermes_sha"], task=row["task"], arm=row["arm"],
            rep=int(row["rep"]), sanitizer_version=SANITIZER_VERSION, artifact_path=artifact,
        )
        bound = attach_binding(trace, binding)
        validate_trace_binding(bound, registry, artifact_path=artifact)
        if validate_trace(bound):
            raise ValueError(f"invalid bound toolperf trace: {key}")
        clean, redaction = _sanitize_bound_trace(bound, corpus_id)
        traces.append(clean)
        bindings.append(binding)
        reports.append(redaction)
    written = _write_corpus(out_root, registry.require(corpus_id), traces, bindings, reports)
    gate = {
        "runs": len(payload["runs"]), "metric_fidelity": payload["gate1_metric_matches"],
        "mismatches": len(payload["mismatches"]), "run_identities_unchanged": current_ids == frozen_ids,
        "source_checksums_unchanged": True, "archive_sha256": sha256_file(artifact),
    }
    return written, gate


def _local_result_path(corpus_id: str) -> Path:
    if corpus_id == "local-qwen38-zero-toolset-warning-v1":
        return REPO_ROOT / "results/20260820T225846Z/zero-toolset-live/ed5b9152ce975ada68f0b53a21c4806f29ed0852/result.json"
    return REPO_ROOT / "results/v0.5-cells" / corpus_id / "result.json"


def ingest_local_corpus(registry: CorpusRegistry, out_root: Path, corpus_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = registry.verify_artifact(corpus_id)
    trace = _json(artifact)
    result = _json(_local_result_path(corpus_id))
    errors = validate_trace(trace)
    if errors:
        raise ValueError(f"invalid frozen local trace {corpus_id}: {errors}")
    manifest = registry.require(corpus_id)
    spans = sorted({str(event.get("span_id")) for event in trace["events"] if event.get("span_id")})
    traces: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    counts = Counter()
    for span in spans:
        arm, rep_text = span.split(":", 1)
        rep = int(rep_text)
        subset = _span_trace(trace, span)
        state = next((event.get("payload", {}) for event in subset["events"] if event.get("type") == "state.snapshot"), {})
        counts[f"{arm}_runs"] += 1
        counts[f"{arm}_success"] += int(bool(state.get("task_success")))
        counts[f"{arm}_tool_calls"] += sum(event.get("type") == "tool.call" for event in subset["events"])
        counts[f"{arm}_tool_results"] += sum(event.get("type") == "tool.result" for event in subset["events"])
        binding = build_binding(
            registry, corpus_id=corpus_id, source_run_identity=f"{trace['run_id']}#{span}",
            model=str(trace.get("provenance", {}).get("model") or result.get("model") or "NOT_RECORDED"),
            hermes_sha=str(trace.get("provenance", {}).get("hermes_sha")), task="zero-toolset-live",
            arm=arm, rep=rep, sanitizer_version=SANITIZER_VERSION, artifact_path=artifact,
        )
        bound = attach_binding(subset, binding)
        validate_trace_binding(bound, registry, artifact_path=artifact)
        clean, redaction = _sanitize_bound_trace(bound, corpus_id)
        traces.append(clean)
        bindings.append(binding)
        reports.append(redaction)
    baseline = _json(REPO_ROOT / "results" / "baselines" / corpus_id / "manifest.json")
    frozen_cell = baseline.get("cell") or {}
    expected = {
        "control_runs": int(frozen_cell.get("n_control", frozen_cell.get("n_behavioral", 10))),
        "fault_runs": int(frozen_cell.get("n_fault", frozen_cell.get("n_behavioral", 10))),
        "control_success": int(frozen_cell.get("control_task_success", frozen_cell.get("control_success", 0))),
        "fault_success": int(frozen_cell.get("fault_task_success", frozen_cell.get("fault_success", 0))),
        "control_tool_calls": int(frozen_cell.get("control_tool_calls", 0)),
        "control_tool_results": int(frozen_cell.get("control_tool_results", 0)),
        "fault_tool_calls": int(frozen_cell.get("fault_tool_calls", 0)),
        "fault_tool_results": int(frozen_cell.get("fault_tool_results", 0)),
    }
    for key, value in expected.items():
        if counts.get(key, 0) != value:
            raise ValueError(f"local cell drift {corpus_id} {key}: {counts.get(key, 0)} != {value}")
    written = _write_corpus(out_root, manifest, traces, bindings, reports)
    response_flags = Counter()
    for event in trace["events"]:
        if event.get("type") != "model.response" or not str(event.get("span_id", "")).startswith("fault:"):
            continue
        payload = event.get("payload", {})
        for key in ("textual_pseudo_tool_call", "hallucinated_completion", "explicit_capability_failure", "remediation_requested", "other_tool_like_text", "plain_failure_other"):
            response_flags[key] += int(bool(payload.get(key)))
    gate = {
        "trace_valid": True, "artifact_sha256": sha256_file(artifact), "counts": dict(counts),
        "behavior_components": dict(response_flags),
        "behavior_gap": "corrected v0.5 categories are readout-only; transcript omitted from TraceV1" if corpus_id == "local-qwen38-zero-toolset-warning-v1" else None,
    }
    return written, gate


def ingest_known_corpora(out_root: Path | None = None) -> dict[str, Any]:
    out_root = (out_root or REPO_ROOT / "results" / "corpus").resolve()
    registry = CorpusRegistry.load()
    written: list[dict[str, Any]] = []
    gates: dict[str, Any] = {}
    item, gate = ingest_toolperf_corpus(registry, out_root)
    written.append(item); gates[item["corpus_id"]] = gate
    for corpus_id in LOCAL_CORPORA:
        item, gate = ingest_local_corpus(registry, out_root, corpus_id)
        written.append(item); gates[corpus_id] = gate
    # The deterministic source is registered and checksum-verified but is not
    # mined as production behavior.
    deterministic = registry.verify_artifact("core-failures-historical-v1")
    _dump(out_root / "core-failures-historical-v1" / "manifest.json", registry.require("core-failures-historical-v1"))
    gates["core-failures-historical-v1"] = {"artifact_sha256": sha256_file(deterministic), "registered_only": True}
    report = {
        "schema": "CorpusIngestionReportV1", "sanitizer_version": SANITIZER_VERSION,
        "corpora": written, "gates": gates,
        "all_safe_to_commit": all(row["safe_to_commit"] for row in written),
        "toolperf_108_of_108": gates["toolperf-2026-08-06"]["metric_fidelity"] == 108,
    }
    _dump(out_root / "ingestion-report.json", report)
    return report


if __name__ == "__main__":
    print(json.dumps(ingest_known_corpora(), indent=2, sort_keys=True))
