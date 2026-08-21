"""v0.4 analysis + live classifiers. No Hermes SUT required."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evals.runners import zero_toolset
from evals.runners.zero_toolset_live import _clear_attempt_artifacts, _config
from hermes_eval.analyze import analyze_live_result, analyze_toolperf_sanity
from hermes_eval.behavior import (
    MIN_N_FOR_RATE,
    classify_fault_text,
    classify_pseudo_tool,
    control_cell_validity,
    efficiency_given_success,
    is_infra_startup_failure,
    retries_after_error,
    should_retry_infra,
)
from hermes_eval.stats import wilson_interval
from hermes_eval.trace.adapters.native import emit_live_run, emit_native
from hermes_eval.trace.model import validate_trace
from hermes_eval.trace.rescore import score_trace


class WilsonAndPolicyTests(unittest.TestCase):
    def test_wilson_known_values(self):
        all_ok = wilson_interval(10, 10)
        self.assertEqual(all_ok["rate"], 1.0)
        self.assertGreaterEqual(all_ok["ci95"][0], 0.65)
        self.assertEqual(all_ok["ci95"][1], 1.0)
        none = wilson_interval(0, 10)
        self.assertEqual(none["rate"], 0.0)
        self.assertEqual(none["ci95"][0], 0.0)
        self.assertLessEqual(none["ci95"][1], 0.35)

    def test_min_n_policy(self):
        self.assertEqual(MIN_N_FOR_RATE, 5)
        bad = control_cell_validity(0, 4)
        self.assertFalse(bad["valid"])
        invalid = control_cell_validity(2, 10)
        self.assertFalse(invalid["valid"])
        ok = control_cell_validity(8, 10)
        self.assertTrue(ok["valid"])

    def test_efficiency_excludes_failures(self):
        rows = [
            {"task_success": True, "turns": 6, "actual_tool_calls": 4, "total_tokens": 100, "duration_ms": 1000},
            {"task_success": False, "turns": 2, "actual_tool_calls": 0, "total_tokens": 20, "duration_ms": 200},
        ]
        eff = efficiency_given_success(rows)
        self.assertEqual(eff["n_success"], 1)
        self.assertEqual(eff["turns"]["median"], 6)
        self.assertEqual(eff["n_fail"], 1)


class ClassifierTests(unittest.TestCase):
    def test_pseudo_syntax_split(self):
        json_blob = '{"name": "write_file", "arguments": {"path": "x"}}'
        xml_blob = "<function=write_file>path=x"
        other = "invoke write_file now"
        j = classify_pseudo_tool(json_blob, actual_tool_calls=0)
        x = classify_pseudo_tool(xml_blob, actual_tool_calls=0)
        o = classify_pseudo_tool(other, actual_tool_calls=0)
        self.assertTrue(j["pseudo_json_like"])
        self.assertFalse(j["pseudo_xml_function"])
        self.assertTrue(x["pseudo_xml_function"])
        self.assertFalse(x["pseudo_json_like"])
        self.assertTrue(o["pseudo_other"])
        self.assertFalse(o["pseudo_json_like"])
        none = classify_pseudo_tool(json_blob, actual_tool_calls=1)
        self.assertFalse(none["textual_pseudo_tool_call"])

    def test_fault_text_classes_stay_separate(self):
        text = (
            "I cannot write files; no tools are available. "
            "Please enable the cli toolset. "
            "<function=write_file> "
            "I've created proof.txt successfully. "
            "empty toolset list"
        )
        flags = classify_fault_text(text, task_success=False, actual_tool_calls=0)
        self.assertTrue(flags["pseudo_xml_function"])
        self.assertTrue(flags["hallucinated_completion"])
        self.assertTrue(flags["explicit_capability_failure"])
        self.assertTrue(flags["remediation_requested"])
        self.assertTrue(flags["diagnostic_emitted"])

    def test_hallucinated_completion_catches_terse_file_claims(self):
        claims = (
            "Done. Created /tmp/proof.txt containing exactly: NONCE",
            "Done. File written: /tmp/proof.txt Content: NONCE",
            "Done. File written to /tmp/proof.txt",
            "Created the file at /tmp/proof.txt containing exactly NONCE.",
            "I've created the file at /tmp/proof.txt.",
        )
        for text in claims:
            with self.subTest(text=text):
                flags = classify_fault_text(text, task_success=False, actual_tool_calls=0)
                self.assertTrue(flags["hallucinated_completion"])
        self.assertFalse(
            classify_fault_text(
                "Let me first check whether a file-writing tool is available.",
                task_success=False,
                actual_tool_calls=0,
            )["hallucinated_completion"]
        )

    def test_textual_protocol_catches_function_style_file_pseudo_calls(self):
        for text in (
            "fileedit(path='/tmp/proof.txt', content='NONCE')",
            "write(path='/tmp/proof.txt', content='NONCE')",
            "write_file(file_path='/tmp/proof.txt', content='NONCE')",
        ):
            with self.subTest(text=text):
                flags = classify_fault_text(text, task_success=False, actual_tool_calls=0)
                self.assertTrue(flags["textual_pseudo_tool_call"])
                self.assertTrue(flags["pseudo_other"])
        self.assertFalse(
            classify_fault_text(
                "echo NONCE > /tmp/proof.txt",
                task_success=False,
                actual_tool_calls=0,
            )["textual_pseudo_tool_call"]
        )

    def test_config_writes_reasoning_effort(self):
        yaml = _config(
            "openrouter",
            "cheap-model",
            None,
            {"cli": []},
            temperature=0.0,
            reasoning="none",
        )
        self.assertIn("reasoning_effort: none", yaml)
        self.assertIn("temperature: 0.0", yaml)

    def test_clear_attempt_artifacts_drops_stale_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            proof = Path(tmp) / "proof.txt"
            proof.write_text("LIVE-stale", encoding="utf-8")
            _clear_attempt_artifacts(proof)
            self.assertFalse(proof.exists())

    def test_zero_toolset_uses_one_canonical_proof_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            seen: dict[str, object] = {}

            def fake_dispatch(_root: Path, proof: Path, nonce: str):
                seen["proof"] = proof
                proof.write_text(nonce, encoding="utf-8")
                return True, "ok"

            with (
                patch.object(zero_toolset, "_warnings", return_value=[]),
                patch.object(zero_toolset, "_resolve_tool_names", return_value=["write_file"]),
                patch.object(zero_toolset, "_dispatch_write_file", side_effect=fake_dispatch),
            ):
                row = zero_toolset._run_arm(
                    hermes_root=workspace,
                    arm="control",
                    platform_toolsets={"cli": ["hermes-cli"]},
                    workspace=workspace,
                )
            canonical = (workspace / "proof.txt").resolve()
            self.assertEqual(seen["proof"], canonical)
            self.assertEqual(Path(row["proof_path"]), canonical)
            self.assertTrue(row["proof_exists"])
            self.assertEqual(canonical.read_text(encoding="utf-8"), row["nonce"])

    def test_zero_toolset_applies_isolated_home_in_process(self):
        seen_homes: list[str | None] = []

        def fake_arm(*, arm: str, workspace: Path, **_kwargs):
            seen_homes.append(os.environ.get("HERMES_HOME"))
            return {
                "arm": arm,
                "proof_exists": arm == "control",
                "proof_path": str((workspace / "proof.txt").resolve()),
                "tool_schema_count": 1 if arm == "control" else 0,
                "tool_calls": 1 if arm == "control" else 0,
                "tool_calls_success": 1 if arm == "control" else 0,
                "tool_calls_failed": 0,
                "invalid_tool_calls": 0,
                "textual_pseudo_tool_call": arm == "fault",
                "warning_emitted": arm == "fault",
            }

        with patch.object(zero_toolset, "_run_arm", side_effect=fake_arm):
            result = zero_toolset.run(Path("/sut"), "sha", Path("/unused"))
        self.assertEqual(seen_homes, [result["extras"]["hermes_home"]] * 2)

    def test_infra_retry_boundary(self):
        self.assertTrue(
            is_infra_startup_failure(
                exit_code=1,
                stderr="ModuleNotFoundError: no module named hermes_cli",
                usage={},
                started=True,
            )
        )
        self.assertFalse(
            is_infra_startup_failure(
                exit_code=0,
                stderr="",
                usage={"api_calls": 1},
                started=True,
            )
        )
        self.assertTrue(should_retry_infra(0, infra=True))
        self.assertFalse(should_retry_infra(1, infra=True))
        self.assertFalse(should_retry_infra(0, infra=False))

    def test_identical_retry_vs_changed_args(self):
        events = [
            {"name": "write_file", "status": "error", "arguments": {"path": "a"}},
            {"name": "write_file", "status": "ok", "arguments": {"path": "a"}},
            {"name": "write_file", "status": "error", "arguments": {"path": "a"}},
            {"name": "write_file", "status": "ok", "arguments": {"path": "b"}},
        ]
        counts = retries_after_error(events)
        self.assertEqual(counts["retries_after_error"], 2)
        self.assertEqual(counts["identical_retries_after_error"], 1)


class LiveAnalysisTests(unittest.TestCase):
    def test_blocked_does_not_invent_rates(self):
        result = {
            "fixture": "zero-toolset-live",
            "status": "BLOCKED",
            "success": False,
            "extras": {"blocked_reason": "missing HERMES_EVAL_API_KEY"},
        }
        analysis = analyze_live_result(result)
        self.assertEqual(analysis["status"], "BLOCKED")
        self.assertIsNone(analysis["control"])
        self.assertIsNone(analysis["fault"])
        self.assertFalse(analysis["synthetic_substitution"])
        self.assertEqual(analysis["observatory"], "NOT READY")
        scored = score_trace(emit_native(result))
        self.assertEqual(scored["status"], "BLOCKED")

    def test_invalid_control_withholds_fault_interpretation(self):
        result = self._live_result(control_ok=1, n=10)
        analysis = analyze_live_result(result)
        self.assertEqual(analysis["status"], "RUN")
        self.assertFalse(analysis["cell_valid_for_fault_comparison"])
        self.assertIsNone(analysis["fault"])
        self.assertIsNotNone(analysis["fault_raw"])

    def test_valid_control_reports_fault_modes(self):
        result = self._live_result(control_ok=9, n=10, fault_xml=True)
        analysis = analyze_live_result(result)
        self.assertTrue(analysis["cell_valid_for_fault_comparison"])
        self.assertIsNotNone(analysis["fault"])
        xml = analysis["fault"]["failure_modes"]["pseudo_xml_function"]
        self.assertEqual(xml["rate"], 1.0)
        self.assertEqual(analysis["pass_at_k"], "not_computed_n_too_small")

    def test_infra_startup_excluded_from_fault_rates(self):
        result = self._live_result(control_ok=9, n=10, fault_xml=True)
        result["extras"]["fault_runs"].append(
            {
                "arm": "fault",
                "task_success": False,
                "infra_startup_failure": True,
                "failure_class": "infra_startup",
                "textual_pseudo_tool_call": False,
                "pseudo_xml_function": False,
                "diagnostic_emitted": False,
                "turns": 0,
            }
        )
        analysis = analyze_live_result(result)
        self.assertEqual(analysis["fault"]["n"], 10)
        self.assertEqual(analysis["fault"]["n_infra_startup"], 1)
        self.assertEqual(analysis["fault"]["failure_modes"]["pseudo_xml_function"]["n"], 10)
        self.assertEqual(analysis["fault"]["failure_modes"]["pseudo_xml_function"]["rate"], 1.0)

    def test_per_run_trace_has_required_events(self):
        result = self._live_result(control_ok=1, n=1)
        row = result["extras"]["control_runs"][0]
        trace = emit_live_run(result, row, arm="control", index=0)
        self.assertEqual(validate_trace(trace), [])
        types = {e["type"] for e in trace["events"]}
        self.assertIn("model.request", types)
        self.assertIn("model.response", types)
        self.assertIn("tool.call", types)
        self.assertIn("tool.result", types)
        self.assertIn("final.output", types)
        finals = [e for e in trace["events"] if e["type"] == "final.output"]
        self.assertTrue(finals[-1]["payload"]["proof_exists"])

    @staticmethod
    def _live_result(*, control_ok: int, n: int, fault_xml: bool = False) -> dict:
        control = []
        fault = []
        for i in range(n):
            ok = i < control_ok
            control.append(
                {
                    "arm": "control",
                    "task_success": ok,
                    "proof_exists": ok,
                    "actual_tool_calls": 1 if ok else 0,
                    "successful_tool_calls": 1 if ok else 0,
                    "failed_tool_calls": 0,
                    "turns": 3 if ok else 1,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "duration_ms": 800,
                    "tool_schema_count": 1,
                    "tool_events": [{"name": "write_file", "status": "ok"}] if ok else [],
                    "model": "test-model",
                    "provider": "openrouter",
                    "temperature": 0,
                }
            )
            fault.append(
                {
                    "arm": "fault",
                    "task_success": False,
                    "proof_exists": False,
                    "actual_tool_calls": 0,
                    "textual_pseudo_tool_call": fault_xml,
                    "pseudo_xml_function": fault_xml,
                    "pseudo_json_like": False,
                    "pseudo_other": False,
                    "hallucinated_completion": False,
                    "explicit_capability_failure": True,
                    "remediation_requested": False,
                    "diagnostic_emitted": True,
                    "turns": 2,
                    "total_tokens": 40,
                    "duration_ms": 400,
                    "tool_schema_count": 0,
                    "tool_events": [],
                    "model": "test-model",
                    "provider": "openrouter",
                    "temperature": 0,
                }
            )
        return {
            "fixture": "zero-toolset-live",
            "status": "RUN",
            "success": True,
            "hermes_ref": "13ce0c5c675e843af70d19c9e5144249cd51c8d1",
            "model": "test-model",
            "provider": "openrouter",
            "timestamp": "2026-08-20T00:00:00+00:00",
            "extras": {
                "reps": n,
                "control_runs": control,
                "fault_runs": fault,
                "control_task_success_rate": control_ok / n,
                "fault_task_success_rate": 0.0,
                "model_params": {"temperature": 0, "reasoning": None},
            },
        }


class ToolperfSanityTests(unittest.TestCase):
    def test_recovery_and_case_search(self):
        ingest_path = REPO / "results" / "toolperf-ingest.json"
        if not ingest_path.is_file():
            self.skipTest("results/toolperf-ingest.json not present")
        import json

        ingest = json.loads(ingest_path.read_text(encoding="utf-8"))
        sanity = analyze_toolperf_sanity(ingest)
        self.assertTrue(sanity["passed"], sanity)
        tasks = {row["task"]: row for row in sanity["recovery_worth_extra_turns"]}
        for name in ("err_inline_script", "err_big_output", "err_big_file_read"):
            self.assertTrue(tasks[name]["passed"], name)
            self.assertEqual(tasks[name]["story"], "recovery_worth_extra_turns")
        case = sanity["err_case_search"]
        self.assertTrue(case["passed"])
        self.assertEqual(case["story"], "same_success_efficiency_regression")
        self.assertEqual(case["baseline"]["success"]["rate"], 1.0)
        self.assertEqual(case["fixes"]["success"]["rate"], 1.0)
        self.assertLess(
            case["baseline"]["llm_given_success"]["median"],
            case["fixes"]["llm_given_success"]["median"],
        )


if __name__ == "__main__":
    unittest.main()
