"""Explicit CorpusManifestV1 binding for every imported TraceV1 run."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from hermes_eval.corpus.registry import CorpusRegistry, manifest_sha256
from hermes_eval.schema import validate_contract

BINDING_KEY = "corpus_binding"


def build_binding(
    registry: CorpusRegistry,
    *,
    corpus_id: str,
    source_run_identity: str,
    model: str | None,
    hermes_sha: str,
    task: str,
    arm: str,
    rep: int,
    sanitizer_version: int,
    artifact_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build a binding only after the declared raw artifact verifies exactly."""
    manifest = registry.require(corpus_id)
    registry.verify_artifact(corpus_id, artifact_path)
    binding = {
        "schema": "CorpusTraceBindingV1",
        "schema_version": 1,
        "corpus_id": corpus_id,
        "manifest_sha256": manifest_sha256(manifest),
        "raw_artifact_sha256": manifest["raw_artifact_sha256"],
        "adapter_version": manifest["adapter_version"],
        "sanitizer_version": sanitizer_version,
        "trace_schema": manifest["trace_schema"],
        "source_run_identity": source_run_identity,
        "model": model,
        "hermes_sha": hermes_sha,
        "task": task,
        "arm": arm,
        "rep": rep,
    }
    validate_contract(binding, "CorpusTraceBindingV1")
    return binding


def validate_binding(
    binding: dict[str, Any],
    registry: CorpusRegistry,
    *,
    artifact_path: Path | str | None = None,
) -> None:
    validate_contract(binding, "CorpusTraceBindingV1")
    manifest = registry.require(str(binding["corpus_id"]))
    expected_manifest = manifest_sha256(manifest)
    if binding["manifest_sha256"] != expected_manifest:
        raise ValueError(
            f"manifest checksum mismatch for {binding['corpus_id']}: "
            f"expected {expected_manifest}, got {binding['manifest_sha256']}"
        )
    if binding["raw_artifact_sha256"] != manifest["raw_artifact_sha256"]:
        raise ValueError(f"raw checksum binding mismatch for {binding['corpus_id']}")
    if binding["adapter_version"] != manifest["adapter_version"]:
        raise ValueError(f"adapter version mismatch for {binding['corpus_id']}")
    if binding["trace_schema"] != manifest["trace_schema"]:
        raise ValueError(f"trace schema mismatch for {binding['corpus_id']}")
    if artifact_path is not None:
        registry.verify_artifact(str(binding["corpus_id"]), artifact_path)


def attach_binding(trace: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a TraceV1 document with one explicit corpus binding."""
    validate_contract(binding, "CorpusTraceBindingV1")
    bound = copy.deepcopy(trace)
    provenance = bound.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("TraceV1 provenance is required before corpus binding")
    if BINDING_KEY in provenance:
        raise ValueError("TraceV1 already has a corpus binding")
    provenance[BINDING_KEY] = copy.deepcopy(binding)
    return bound


def validate_trace_binding(
    trace: dict[str, Any],
    registry: CorpusRegistry,
    *,
    artifact_path: Path | str | None = None,
) -> dict[str, Any]:
    provenance = trace.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get(BINDING_KEY), dict):
        raise ValueError("TraceV1 is missing explicit corpus_binding provenance")
    binding = provenance[BINDING_KEY]
    validate_binding(binding, registry, artifact_path=artifact_path)
    return binding

