from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.corpus.binding import (
    attach_binding,
    build_binding,
    validate_binding,
    validate_trace_binding,
)
from hermes_eval.corpus.registry import CorpusRegistry
from hermes_eval.schema import validation_errors


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _manifest(raw_sha: str, location: str = "raw.json") -> dict:
    return {
        "schema": "CorpusManifestV1",
        "schema_version": 1,
        "corpus_id": "test-corpus-v1",
        "source_class": "local_reproduction",
        "source_repo": None,
        "source_ref": None,
        "license": "test",
        "consent": "owner_generated",
        "privacy_class": "synthetic_task",
        "retrieved_at": "2026-08-21T00:00:00Z",
        "raw_artifact_sha256": raw_sha,
        "adapter": "test.adapter",
        "adapter_version": "1",
        "trace_schema": "TraceV1",
        "retention": "local_only",
        "committable": False,
        "safe_to_commit": False,
        "identity": {"kind": "artifact_sha256", "value": raw_sha},
        "retrieval": {"method": "explicit_export", "location": location},
        "redaction": None,
        "provenance": None,
        "notes": [],
    }


def _write_registry(root: Path, manifest: dict) -> Path:
    path = root / "registry.json"
    path.write_text(
        json.dumps(
            {"schema": "CorpusRegistryV1", "schema_version": 1, "corpora": [manifest]}
        ),
        encoding="utf-8",
    )
    return path


class CorpusRegistryTests(unittest.TestCase):
    def test_repository_registry_declares_all_required_sources_and_verifies(self):
        registry = CorpusRegistry.load()
        self.assertEqual(
            set(registry.manifests),
            {
                "toolperf-2026-08-06",
                "local-qwen38-zero-toolset-silent-v1",
                "local-qwen38-zero-toolset-warning-v1",
                "local-qwen35-9b-zero-toolset-silent-v1",
                "local-qwen35-9b-zero-toolset-warning-v1",
                "core-failures-historical-v1",
            },
        )
        for corpus_id in registry.manifests:
            self.assertTrue(registry.verify_artifact(corpus_id).is_file())

    def test_registry_rejects_path_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = b"{}\n"
            (root / "raw.json").write_bytes(raw)
            manifest = _manifest(_sha(raw))
            manifest["identity"] = {"kind": "path", "value": "/tmp/raw.json"}
            with self.assertRaises(ValueError):
                CorpusRegistry.load(_write_registry(root, manifest), repo_root=root)

    def test_checksum_change_is_not_silently_refreshed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "raw.json"
            artifact.write_bytes(b"first\n")
            registry = CorpusRegistry.load(
                _write_registry(root, _manifest(_sha(b"first\n"))), repo_root=root
            )
            registry.verify_artifact("test-corpus-v1")
            artifact.write_bytes(b"second\n")
            with self.assertRaisesRegex(ValueError, "new corpus version"):
                registry.verify_artifact("test-corpus-v1")

    def test_binding_requires_registered_manifest_and_exact_raw_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "raw.json"
            artifact.write_bytes(b"trace\n")
            registry = CorpusRegistry.load(
                _write_registry(root, _manifest(_sha(b"trace\n"))), repo_root=root
            )
            binding = build_binding(
                registry,
                corpus_id="test-corpus-v1",
                source_run_identity="source/run/1",
                model="model-a",
                hermes_sha="a" * 40,
                task="task-a",
                arm="fault",
                rep=1,
                sanitizer_version=1,
            )
            validate_binding(binding, registry, artifact_path=artifact)

            unknown = copy.deepcopy(binding)
            unknown["corpus_id"] = "missing-corpus"
            with self.assertRaisesRegex(ValueError, "unregistered"):
                validate_binding(unknown, registry)

            changed = copy.deepcopy(binding)
            changed["raw_artifact_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "raw checksum"):
                validate_binding(changed, registry)

    def test_binding_has_explicit_source_coordinates_and_attaches_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.json").write_bytes(b"trace\n")
            registry = CorpusRegistry.load(
                _write_registry(root, _manifest(_sha(b"trace\n"))), repo_root=root
            )
            binding = build_binding(
                registry,
                corpus_id="test-corpus-v1",
                source_run_identity="source/run/1",
                model="model-a",
                hermes_sha="a" * 40,
                task="task-a",
                arm="control",
                rep=0,
                sanitizer_version=1,
            )
            for required in ("model", "hermes_sha", "task", "arm", "rep"):
                invalid = copy.deepcopy(binding)
                invalid.pop(required)
                self.assertTrue(validation_errors(invalid), required)

            trace = {"trace_version": "trace-v1", "provenance": {"source": "atof", "adapter": "x"}}
            bound = attach_binding(trace, binding)
            self.assertNotIn("corpus_binding", trace["provenance"])
            self.assertEqual(validate_trace_binding(bound, registry), binding)
            with self.assertRaisesRegex(ValueError, "already"):
                attach_binding(bound, binding)

            with self.assertRaisesRegex(ValueError, "missing explicit"):
                validate_trace_binding(trace, registry)


if __name__ == "__main__":
    unittest.main()
