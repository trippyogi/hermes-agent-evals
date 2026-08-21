from __future__ import annotations

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.corpus.sanitize import scan_sanitized
from hermes_eval.schema import validate_contract


class V06AdjudicationPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = json.loads((REPO / "results/adjudication/v0.6-production-episodes-v1.json").read_text(encoding="utf-8"))

    def test_packet_is_exactly_at_human_stop(self):
        self.assertEqual(self.packet["status"], "WAITING_FOR_HUMAN_LABELS")
        self.assertEqual(self.packet["unique_episodes"], 50)
        self.assertEqual(len(self.packet["episodes"]), 50)
        for episode in self.packet["episodes"]:
            self.assertIsNone(episode["human_verdict"])
            self.assertIsNone(episode["human_reason"])
            self.assertIsNone(episode["relationship_to_outcome"])
            validate_contract(episode, "EpisodeV1")

    def test_sampling_constraints_and_context(self):
        tasks = Counter(episode["task_id"] for episode in self.packet["episodes"])
        detectors = Counter(detector for episode in self.packet["episodes"] for detector in episode["detectors"])
        self.assertLessEqual(max(tasks.values()) / 50, 0.40)
        self.assertLessEqual(max(detectors.values()) / 50, 0.40)
        self.assertGreaterEqual(len({episode["corpus_id"] for episode in self.packet["episodes"]}), 2)
        self.assertGreaterEqual(len({episode["model"] for episode in self.packet["episodes"]}), 2)
        self.assertIn("success", {episode["outcome"] for episode in self.packet["episodes"]})
        self.assertIn("failure", {episode["outcome"] for episode in self.packet["episodes"]})
        self.assertTrue(any(not episode["detectors"] for episode in self.packet["episodes"]))
        self.assertTrue(any(episode["detectors"] for episode in self.packet["episodes"]))
        for episode in self.packet["episodes"]:
            self.assertIn("candidate_action", episode["context"])
            self.assertIn("new_information_acquired", episode["context"])

    def test_pkg_identity_controls_preserve_distinct_arguments(self):
        controls = [
            episode for episode in self.packet["episodes"]
            if episode["evidence"].get("previous_false_positive_class") == "W3/W5"
        ]
        self.assertEqual(len(controls), 6)
        for episode in controls:
            previous = episode["context"]["previous_action"]
            candidate = episode["context"]["candidate_action"]
            self.assertNotEqual(previous["canonical_arguments"], candidate["canonical_arguments"])
            self.assertTrue(episode["context"]["arguments_changed"])
            self.assertTrue(episode["context"]["new_information_acquired"])

    def test_packet_and_report_pass_privacy_gate(self):
        self.assertTrue(self.packet["redaction"]["safe_to_commit"])
        self.assertEqual(self.packet["redaction"]["findings"], [])
        payload = dict(self.packet)
        payload.pop("redaction", None)  # scanner metadata contains JSON pointers, not source paths
        self.assertEqual(scan_sanitized(payload), [])
        report = (REPO / "reports/evals/v0.6-production-episodes-v1.md").read_text(encoding="utf-8")
        self.assertNotIn("/tmp/", report)
        self.assertIn("WAITING_FOR_HUMAN_LABELS", report)


if __name__ == "__main__":
    unittest.main()
