from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.schema import validate_contract, validation_errors


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
            "retention": "external_read_only", "committable": False,
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
            "model": "model", "server": None, "hermes_sha": "a" * 40, "task_id": "task",
            "start_event_id": "e1", "end_event_id": "e2", "detectors": ["detector-v1"],
            "outcome": "failure", "relationship_to_outcome": "harmful", "evidence": {},
            "human_verdict": None, "human_reason": None
        }
        validate_contract(episode)
        episode["human_verdict"] = "self_labeled"
        self.assertTrue(validation_errors(episode))


if __name__ == "__main__":
    unittest.main()
