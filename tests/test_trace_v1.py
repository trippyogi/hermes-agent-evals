"""TraceV1 unit tests. No Hermes SUT required."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.trace.adapters.atof import emit_atof
from hermes_eval.trace.adapters.native import emit_native
from hermes_eval.trace.model import TRACE_VERSION, TraceBuilder, validate_trace
from hermes_eval.trace.rescore import result_from_trace, score_trace


def _zero_result(*, warning: bool, child_good: bool = True) -> dict:
    control = {
        "arm": "control",
        "tool_schemas": ["write_file"],
        "tool_schema_count": 1,
        "write_file_exposed": True,
        "warning_emitted": False,
        "warnings": [],
        "finish_reason": "stop",
        "textual_pseudo_tool_call": False,
        "transcript": "wrote proof.txt",
        "events": [{"type": "tool", "name": "write_file", "status": "ok"}],
        "tool_calls": 1,
        "proof_exists": True,
    }
    fault = {
        "arm": "fault",
        "tool_schemas": [],
        "tool_schema_count": 0,
        "write_file_exposed": False,
        "warning_emitted": warning,
        "warnings": ["cli: empty toolset list"] if warning else [],
        "finish_reason": "stop",
        "textual_pseudo_tool_call": True,
        "transcript": '{"name": "write_file", "arguments": {"path": "proof.txt"}}',
        "events": [{"type": "llm", "finish_reason": "stop", "tool_schemas": 0}],
        "tool_calls": 0,
        "proof_exists": False,
    }
    return {
        "fixture": "zero-toolset",
        "hermes_ref": "13ce0c5c675e843af70d19c9e5144249cd51c8d1",
        "harness_sha": "deadbeef",
        "success": warning,
        "notes": [],
        "extras": {"control": control, "fault": fault},
    }


def _delegate_result(*, coherent: bool) -> dict:
    child = {
        "provider": "anthropic" if coherent else "openai-codex",
        "model": "claude-sonnet-5" if coherent else "gpt-5.6-sol",
        "base_url": "https://api.anthropic.com" if coherent else "https://chatgpt.com/backend-api/codex",
        "api_mode": "anthropic_messages" if coherent else "codex_responses",
        "credential_class": "anthropic-key" if coherent else "codex-key",
    }
    return {
        "fixture": "delegate-fallback-runtime",
        "hermes_ref": "13ce0c5c675e843af70d19c9e5144249cd51c8d1",
        "success": coherent,
        "notes": [],
        "extras": {
            "fallback_activated": True,
            "child_built": True,
            "fail_closed": False,
            "runtime_coherent": coherent,
            "auth_failures": 0 if coherent else 1,
            "parent_after_fallback": {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "fallback_activated": True,
            },
            "child_runtime": child,
            "expected_child": {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "base_url": "https://api.anthropic.com",
                "api_mode": "anthropic_messages",
                "credential_class": "anthropic-key",
            },
        },
    }


def _pin_result(*, good: bool) -> dict:
    patches = [
        {"op": "patch", "id": "S", "pinned": True, "user_action": True, "profile": "default"},
        {"op": "patch", "id": "S", "pinned": True, "user_action": True, "profile": "k9"},
        {"op": "patch", "id": "S", "pinned": False, "user_action": True, "profile": "default"},
    ]
    if not good:
        patches.append(
            {"op": "patch", "id": "S", "pinned": True, "user_action": False, "profile": "k9"}
        )
    return {
        "fixture": "stale-pin-rescope",
        "hermes_ref": "13ce0c5c675e843af70d19c9e5144249cd51c8d1",
        "success": good,
        "notes": ["pin atom"],
        "extras": {
            "pin_includes_profile": not good,
            "events": [
                {"op": "pin", "id": "S", "profile": "default"},
                {"op": "unpin", "id": "S", "profile": "default"},
                {"op": "rescope", "profile": "k9", "local": ["S"] if not good else []},
            ],
            "patches": patches,
            "local_final": [] if good else ["S"],
            "backend_final": {"S": False} if good else {"S": True},
            "final_unpinned": good,
            "unsolicited_pin_patches": 0 if good else 1,
        },
    }


class TraceV1Tests(unittest.TestCase):
    def test_builder_validates(self):
        b = TraceBuilder(run_id="t", source="synthetic", adapter="test")
        b.event("diagnostic", {"code": "x", "message": "y"})
        trace = b.to_dict()
        self.assertEqual(trace["trace_version"], TRACE_VERSION)
        self.assertEqual(validate_trace(trace), [])

    def test_zero_toolset_from_trace_not_extras(self):
        bad = emit_native(_zero_result(warning=False))
        good = emit_native(_zero_result(warning=True))
        bad["provenance"]["fixture"] = "zero-toolset"
        self.assertFalse(score_trace(bad)["success"])
        self.assertTrue(score_trace(good)["success"])
        # Throw away any leftover extras-equivalent: flipping final_state
        # diagnostic is in events, so deleting extras is already done.
        poisoned = emit_native(_zero_result(warning=True))
        poisoned["metrics"]["cheated"] = True
        self.assertTrue(score_trace(poisoned)["success"])

    def test_zero_ignores_result_success_field(self):
        result = _zero_result(warning=True)
        result["success"] = False
        trace = emit_native(result)
        self.assertTrue(score_trace(trace)["success"])
        result2 = _zero_result(warning=False)
        result2["success"] = True
        self.assertFalse(score_trace(emit_native(result2))["success"])

    def test_delegate_polarities(self):
        self.assertFalse(score_trace(emit_native(_delegate_result(coherent=False)))["success"])
        self.assertTrue(score_trace(emit_native(_delegate_result(coherent=True)))["success"])

    def test_pin_recomputes_unsolicited_from_events(self):
        good = emit_native(_pin_result(good=True))
        bad = emit_native(_pin_result(good=False))
        # Lie in final_state; scorer must use PATCH events.
        good["final_state"]["unsolicited_pin_patches"] = 99
        good["final_state"]["final_unpinned"] = False
        self.assertTrue(score_trace(good)["success"])
        self.assertFalse(score_trace(bad)["success"])

    def test_result_from_trace_has_empty_extras(self):
        scored = result_from_trace(emit_native(_zero_result(warning=True)))
        self.assertEqual(scored["extras"], {})
        self.assertTrue(scored["success"])
        self.assertEqual(scored["scored_from"], "trace-v1")

    def test_atof_adapter(self):
        path = REPO / "evals" / "fixtures" / "_trace_samples" / "atof-sample.jsonl"
        trace = emit_atof(path)
        self.assertEqual(validate_trace(trace), [])
        self.assertEqual(trace["final_state"]["tools"], 3)
        self.assertEqual(trace["final_state"]["retries"], 1)
        self.assertEqual(trace["final_state"]["errs"], 2)

    def test_live_blocked_no_synthetic_rates(self):
        result = {
            "fixture": "zero-toolset-live",
            "status": "BLOCKED",
            "success": False,
            "notes": [],
            "extras": {"blocked_reason": "missing HERMES_EVAL_API_KEY", "reps": None},
        }
        scored = score_trace(emit_native(result))
        self.assertEqual(scored["status"], "BLOCKED")
        self.assertFalse(scored["success"])
        self.assertIsNone(emit_native(result)["final_state"].get("rates"))
        self.assertFalse(scored["metrics"].get("synthetic_substitution"))

    def test_historical_shape_from_traces(self):
        pairs = [
            ("zero-toolset", _zero_result(warning=False), _zero_result(warning=True)),
            ("delegate-fallback-runtime", _delegate_result(coherent=False), _delegate_result(coherent=True)),
            ("stale-pin-rescope", _pin_result(good=False), _pin_result(good=True)),
        ]
        from hermes_eval.compare import build_compare

        scored_pairs = []
        for fixture, bad, good in pairs:
            bad["fixture"] = fixture
            good["fixture"] = fixture
            scored_pairs.append(
                (
                    result_from_trace(emit_native(bad), hermes_ref="bad"),
                    result_from_trace(emit_native(good), hermes_ref="good"),
                )
            )
        report = build_compare(
            suite="core-failures",
            baseline="historical-per-fixture",
            candidate="historical-per-fixture",
            pairs=scored_pairs,
            harness_sha="test",
            historical=False,
        )
        self.assertTrue(report["historical_validation"]["passed"])
        self.assertEqual(report["historical_validation"]["distinguished_count"], 3)
        for row in report["fixtures"]:
            self.assertEqual(row["direction"], "candidate_fixed")


if __name__ == "__main__":
    unittest.main()
