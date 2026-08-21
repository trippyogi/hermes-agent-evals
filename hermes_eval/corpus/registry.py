"""Immutable corpus source registry and raw-artifact verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_eval.gitutil import REPO_ROOT
from hermes_eval.schema import validate_contract

DEFAULT_REGISTRY = REPO_ROOT / "evals" / "corpora" / "registry.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CorpusRegistry:
    manifests: dict[str, dict[str, Any]]
    path: Path
    repo_root: Path

    @classmethod
    def load(
        cls,
        path: Path | str = DEFAULT_REGISTRY,
        *,
        repo_root: Path | str = REPO_ROOT,
    ) -> "CorpusRegistry":
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if set(payload) != {"schema", "schema_version", "corpora"}:
            raise ValueError("corpus registry must contain only schema, schema_version, and corpora")
        if payload.get("schema") != "CorpusRegistryV1" or payload.get("schema_version") != 1:
            raise ValueError("unsupported corpus registry contract")
        rows = payload.get("corpora")
        if not isinstance(rows, list) or not rows:
            raise ValueError("corpus registry must contain at least one manifest")
        manifests: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("corpus registry entries must be objects")
            validate_contract(row, "CorpusManifestV1")
            corpus_id = str(row["corpus_id"])
            if corpus_id in manifests:
                raise ValueError(f"duplicate corpus_id: {corpus_id}")
            if (row.get("identity") or {}).get("kind") not in {
                "repository_ref",
                "artifact_sha256",
                "baseline_id",
            }:
                raise ValueError(f"corpus identity may not be a path: {corpus_id}")
            manifests[corpus_id] = row
        return cls(manifests=manifests, path=source.resolve(), repo_root=Path(repo_root).resolve())

    def require(self, corpus_id: str) -> dict[str, Any]:
        try:
            return self.manifests[corpus_id]
        except KeyError as exc:
            raise ValueError(f"unregistered corpus_id: {corpus_id}") from exc

    def artifact_path(self, corpus_id: str) -> Path:
        manifest = self.require(corpus_id)
        location = (manifest.get("retrieval") or {}).get("location")
        if not location:
            raise ValueError(f"corpus has no local retrieval location: {corpus_id}")
        path = Path(str(location))
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()

    def verify_artifact(self, corpus_id: str, path: Path | str | None = None) -> Path:
        manifest = self.require(corpus_id)
        artifact = Path(path).resolve() if path is not None else self.artifact_path(corpus_id)
        if not artifact.is_file():
            raise ValueError(f"raw artifact missing for {corpus_id}: {artifact}")
        expected = str(manifest["raw_artifact_sha256"])
        observed = sha256_file(artifact)
        if observed != expected:
            raise ValueError(
                f"raw artifact checksum changed for {corpus_id}: expected {expected}, got {observed}; "
                "register a new corpus version instead of refreshing in place"
            )
        return artifact

