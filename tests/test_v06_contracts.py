from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.schema import validate_contract, validation_errors
from hermes_eval.corpus.sanitize import CorpusSanitizer


def _json(path: str) -> dict:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


class V06ContractTests(unittest.TestCase):
    def test_gitworthy_examples_validate(self):
        for name in ("eval-opportunity-v1", "eval-evidence-v1"):
            validate_contract(_json(f"integrations/gitworthy/examples/{name}.example.json"))

    def test_opportunity_rejects_t1_and_ranking_fields(self):
        base = _json("integrations/gitworthy/examples/eval-opportunity-v1.example.json")
        for key, value in (("result", "candidate_fixed"), ("ranking_score", 1), ("gitworthy_verdict", "ACT"), ("merged", True)):
            payload = copy.deepcopy(base)
            payload[key] = value
            self.assertTrue(validation_errors(payload), key)

    def test_evidence_rejects_opportunity_fields(self):
        base = _json("integrations/gitworthy/examples/eval-evidence-v1.example.json")
        for key in ("evalability", "recommended_contribution_mode", "ranking_version", "disposition"):
            payload = copy.deepcopy(base)
            payload[key] = {}
            self.assertTrue(validation_errors(payload), key)

    def test_opportunity_score_and_timestamp_are_checked(self):
        payload = _json("integrations/gitworthy/examples/eval-opportunity-v1.example.json")
        payload["evalability"]["score"] = 1.1
        payload["evaluated_at"] = "yesterday"
        self.assertGreaterEqual(len(validation_errors(payload)), 2)

    def test_corpus_manifest_identity_is_not_local_path(self):
        manifest = {
            "schema": "CorpusManifestV1", "schema_version": 1,
            "corpus_id": "toolperf-2026-08-06", "source_class": "public_atof",
            "source_repo": "NousResearch/hermes-toolperf-evals", "source_ref": "a" * 40,
            "license": "unknown", "consent": "public_repository", "privacy_class": "public_sanitized",
            "retrieved_at": "2026-08-21T00:00:00Z", "raw_artifact_sha256": "a" * 64,
            "adapter": "atof", "adapter_version": "1", "trace_schema": "TraceV1",
            "retention": "external_read_only", "committable": False, "safe_to_commit": False,
            "identity": {"kind": "repository_ref", "value": "NousResearch/hermes-toolperf-evals@" + "a" * 40},
            "retrieval": {"method": "git", "location": "/local/convenience/path"}, "notes": []
        }
        validate_contract(manifest)
        manifest["identity"] = {"kind": "path", "value": "/tmp/corpus"}
        self.assertTrue(validation_errors(manifest))

    def test_episode_contract(self):
        episode = {
            "schema": "EpisodeV1", "schema_version": 1, "episode_id": "ep_deadbeef",
            "trace_id": "trace-1", "corpus_id": "corpus-1", "source_class": "public_atof",
            "source_run_id": "run-1",
            "model": "model", "server": None, "hermes_sha": "a" * 40, "task_id": "task",
            "arm": "fault", "repetition": 0,
            "start_event_id": "e1", "end_event_id": "e2", "sampling_role": "detector_candidate", "detectors": ["detector-v1"],
            "outcome": "failure", "relationship_to_outcome": "harmful", "evidence": {},
            "context": {"previous_action": None, "candidate_action": None, "next_action": None, "arguments_changed": None, "new_information_acquired": None, "state_changed": False, "task_succeeded": False},
            "provenance": {"corpus_manifest_sha256": "b" * 64, "raw_artifact_sha256": "c" * 64, "adapter_version": "1", "sanitizer_version": 1, "trace_schema": "TraceV1"},
            "privacy": {"redaction_version": 1, "safe_to_commit": True},
            "human_verdict": None, "human_reason": None
        }
        validate_contract(episode)
        episode["human_verdict"] = "self_labeled"
        self.assertTrue(validation_errors(episode))

    def test_episode_allows_only_explicit_detector_negative_controls(self):
        episode = {
            "schema": "EpisodeV1", "schema_version": 1, "episode_id": "ep_control",
            "trace_id": "trace-1", "corpus_id": "corpus-1", "source_class": "public_atof", "source_run_id": "run-1",
            "model": "model", "server": None, "hermes_sha": "a" * 40, "task_id": "task", "arm": "control", "repetition": 0,
            "start_event_id": "e1", "end_event_id": "e2", "sampling_role": "negative_control", "detectors": [],
            "outcome": "success", "relationship_to_outcome": None, "evidence": {},
            "context": {"previous_action": None, "candidate_action": None, "next_action": None, "arguments_changed": None, "new_information_acquired": True, "state_changed": True, "task_succeeded": True},
            "provenance": {"corpus_manifest_sha256": "b" * 64, "raw_artifact_sha256": "c" * 64, "adapter_version": "1", "sanitizer_version": 1, "trace_schema": "TraceV1"},
            "privacy": {"redaction_version": 1, "safe_to_commit": True}, "human_verdict": None, "human_reason": None,
        }
        validate_contract(episode)
        episode["detectors"] = ["detector-v1"]
        self.assertTrue(validation_errors(episode))

    def test_committable_manifest_requires_clean_reviewed_redaction(self):
        sanitizer = CorpusSanitizer("local-corpus")
        clean = sanitizer.sanitize({"text": "synthetic"})
        report = sanitizer.report(clean, source_type_known=True, manual_spot_check=True)
        manifest = {
            "schema": "CorpusManifestV1", "schema_version": 1, "corpus_id": "local-corpus", "source_class": "local_live_eval",
            "source_repo": None, "source_ref": None, "license": "owner", "consent": "owner_generated", "privacy_class": "synthetic_task",
            "retrieved_at": "2026-08-21T00:00:00Z", "raw_artifact_sha256": "a" * 64, "model_artifact_sha256": "b" * 64,
            "adapter": "native", "adapter_version": "1", "trace_schema": "TraceV1", "retention": "sanitized_committed",
            "committable": True, "safe_to_commit": True, "identity": {"kind": "baseline_id", "value": "local-corpus"},
            "retrieval": {"method": "local_baseline", "location": None}, "redaction": report, "provenance": {}, "notes": [],
        }
        validate_contract(manifest)
        manifest["redaction"]["findings"] = [{"class": "secret", "pattern": "token"}]
        self.assertTrue(validation_errors(manifest))


if __name__ == "__main__":
    unittest.main()
