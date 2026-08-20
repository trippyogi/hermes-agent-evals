"""ATOF adjudication packet. No self-labels. No SUT required for unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.adjudicate_atof import (
    ALLOWED_VERDICTS,
    labels_complete,
    parse_source,
    score_packet,
)


class AdjudicateAtofTests(unittest.TestCase):
    def test_parse_source_keeps_model_slash(self):
        model, arm, run_id = parse_source(
            "qwen/qwen3-coder-30b-a3b-instruct/fixes/err_big_output-r0"
        )
        self.assertEqual(model, "qwen/qwen3-coder-30b-a3b-instruct")
        self.assertEqual(arm, "fixes")
        self.assertEqual(run_id, "err_big_output-r0")

    def test_unlabeled_packet_is_waiting(self):
        packet = {
            "episodes": [
                {"episode_id": f"TP-2026-08-06-E{i:02d}", "HUMAN_VERDICT": None, "detectors": ["W6"]}
                for i in range(1, 14)
            ]
        }
        self.assertFalse(labels_complete(packet))
        scored = score_packet(packet)
        self.assertEqual(scored["status"], "WAITING_FOR_HUMAN_LABELS")
        self.assertIsNone(scored["precision"])
        self.assertEqual(len(scored["unlabeled_episode_ids"]), 13)

    def test_labeled_packet_precision_no_recall(self):
        episodes = []
        for i in range(1, 7):
            episodes.append(
                {
                    "episode_id": f"E{i:02d}",
                    "detectors": ["W3", "W5"],
                    "HUMAN_VERDICT": "not_waste",
                }
            )
        for i in range(7, 14):
            episodes.append(
                {
                    "episode_id": f"E{i:02d}",
                    "detectors": ["W6"],
                    "HUMAN_VERDICT": "waste",
                }
            )
        scored = score_packet({"episodes": episodes})
        self.assertEqual(scored["status"], "LABELED")
        self.assertEqual(scored["recall"], "unsupported")
        self.assertEqual(scored["population_prevalence"], "unsupported")
        self.assertEqual(scored["composite_score"], "forbidden")
        self.assertEqual(scored["by_detector"]["W6"]["precision_among_decided"], 1.0)
        self.assertEqual(scored["by_detector"]["W3"]["precision_among_decided"], 0.0)
        self.assertEqual(scored["taxonomy"]["W6"]["action"], "KEEP")
        self.assertEqual(scored["taxonomy"]["W6"]["reframe"], "textual_tool_protocol_failure")
        self.assertEqual(scored["taxonomy"]["W3"]["action"], "REFINE")
        self.assertEqual(scored["taxonomy"]["W5"]["action"], "REFINE")
        self.assertEqual(scored["taxonomy"]["W3+W5"]["action"], "MERGE")
        self.assertEqual(scored["metrics"]["textual_tool_protocol_failure"]["count"], 7)
        self.assertEqual(scored["by_detector"]["W1"]["unique_episodes"], 0)
        self.assertEqual(scored["taxonomy"]["W1"]["action"], "KEEP")

    def test_merge_preserves_human_verdicts(self):
        from hermes_eval.adjudicate_atof import merge_human_fields

        fresh = {
            "episodes": [
                {"episode_id": "TP-2026-08-06-E01", "HUMAN_VERDICT": None, "HUMAN_REASON": None}
            ]
        }
        old = {
            "episodes": [
                {
                    "episode_id": "TP-2026-08-06-E01",
                    "HUMAN_VERDICT": "not_waste",
                    "HUMAN_REASON": "parallel distinct reads",
                    "candidate_relationship_to_outcome": "neutral",
                }
            ]
        }
        merged = merge_human_fields(fresh, old)
        self.assertEqual(merged["episodes"][0]["HUMAN_VERDICT"], "not_waste")
        self.assertEqual(merged["episodes"][0]["HUMAN_REASON"], "parallel distinct reads")


if __name__ == "__main__":
    unittest.main()
