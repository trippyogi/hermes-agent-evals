from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.corpus.binding import validate_binding
from hermes_eval.corpus.registry import CorpusRegistry, sha256_file
from hermes_eval.schema import validate_contract


class V06IngestionArtifactTests(unittest.TestCase):
    def test_checked_in_ingestion_report_preserves_frozen_gates(self):
        report = json.loads((REPO / "results/corpus/ingestion-report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["all_safe_to_commit"])
        self.assertTrue(report["toolperf_108_of_108"])
        toolperf = report["gates"]["toolperf-2026-08-06"]
        self.assertEqual(toolperf["metric_fidelity"], 108)
        self.assertEqual(toolperf["mismatches"], 0)
        self.assertTrue(toolperf["run_identities_unchanged"])
        self.assertTrue(toolperf["source_checksums_unchanged"])
        for corpus_id in (
            "local-qwen38-zero-toolset-silent-v1",
            "local-qwen38-zero-toolset-warning-v1",
            "local-qwen35-9b-zero-toolset-silent-v1",
            "local-qwen35-9b-zero-toolset-warning-v1",
        ):
            gate = report["gates"][corpus_id]
            self.assertTrue(gate["trace_valid"])
            self.assertEqual(gate["counts"]["control_runs"], 10)
            self.assertEqual(gate["counts"]["fault_runs"], 10)
            self.assertEqual(gate["counts"]["control_success"], 10)
            self.assertEqual(gate["counts"]["fault_success"], 0)
            self.assertEqual(gate["counts"]["fault_tool_calls"], 0)
            self.assertEqual(gate["counts"]["fault_tool_results"], 0)

    def test_all_generated_manifests_and_bindings_validate(self):
        registry = CorpusRegistry.load()
        report = json.loads((REPO / "results/corpus/ingestion-report.json").read_text(encoding="utf-8"))
        for row in report["corpora"]:
            corpus_id = row["corpus_id"]
            root = REPO / "results/corpus" / corpus_id
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            validate_contract(manifest, "CorpusManifestV1")
            payload = json.loads((root / "bindings.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["bindings"]), row["binding_count"])
            for binding in payload["bindings"]:
                validate_binding(binding, registry)
            self.assertEqual(sha256_file(root / "traces.jsonl"), row["traces_sha256"])
            redaction = json.loads((root / "redaction.json").read_text(encoding="utf-8"))
            self.assertTrue(redaction["safe_to_commit"])
            self.assertEqual(redaction["findings"], [])


if __name__ == "__main__":
    unittest.main()
