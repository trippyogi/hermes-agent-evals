from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.gitworthy_boundary import (  # noqa: E402
    BoundaryError,
    POST_OUTCOME_FIELDS,
    VERDICT_FIELDS,
    assert_pinned_boundary,
    inspect_gitworthy,
)
from hermes_eval.schema import validate_contract, validation_errors  # noqa: E402


def _json(path: str) -> dict:
    return json.loads((REPO / path).read_text(encoding="utf-8"))


class GitWorthyBoundaryTests(unittest.TestCase):
    def test_pinned_authoritative_git_objects_match(self):
        sibling = REPO.parents[1] / "repos" / "gitworthy"
        if not (sibling / ".git").exists():
            self.skipTest("read-only sibling GitWorthy checkout is unavailable")
        manifest = _json("integrations/gitworthy/gitworthy-boundary-v1.json")
        observed = assert_pinned_boundary(sibling, manifest)
        self.assertEqual(observed["gitworthy"]["ranking_version"], "1")
        self.assertEqual(observed["frozen_eval"]["case_count"], 31)

    def test_phase_discriminators_are_required_and_distinct(self):
        opportunity = _json("integrations/gitworthy/examples/eval-opportunity-v1.example.json")
        evidence = _json("integrations/gitworthy/examples/eval-evidence-v1.example.json")
        validate_contract(opportunity)
        validate_contract(evidence)
        for payload, wrong in ((opportunity, "T1"), (evidence, "T0")):
            changed = copy.deepcopy(payload)
            changed["information_phase"] = wrong
            self.assertTrue(validation_errors(changed))
            changed = copy.deepcopy(payload)
            del changed["information_phase"]
            self.assertTrue(validation_errors(changed))

    def test_t0_rejects_post_outcome_and_verdict_fields(self):
        opportunity = _json("integrations/gitworthy/examples/eval-opportunity-v1.example.json")
        for key in sorted(POST_OUTCOME_FIELDS | VERDICT_FIELDS):
            changed = copy.deepcopy(opportunity)
            changed[key] = "forbidden"
            self.assertTrue(validation_errors(changed), key)

    def test_t1_rejects_opportunity_and_verdict_fields(self):
        evidence = _json("integrations/gitworthy/examples/eval-evidence-v1.example.json")
        for key in ("evalability", "recommended_contribution_mode", "required_checks", *sorted(VERDICT_FIELDS)):
            changed = copy.deepcopy(evidence)
            changed[key] = "forbidden"
            self.assertTrue(validation_errors(changed), key)

    def test_verifier_fails_closed_on_production_bridge_reference(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "eval@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Eval Test"], cwd=repo, check=True)
            files = {
                "package.json": '{"version":"1.0.0"}\n',
                "src/core/rank.ts": "export const RANKING_VERSION = '1' as const;\n",
                "src/core/worth-check.ts": "import { EvalOpportunity } from '../../integrations/gitworthy/bridge.js';\n",
                "src/core/scan.ts": "export {};\n",
                "src/core/hunt.ts": "export {};\n",
                "src/decision/policy.ts": "export {};\n",
                "eval/frozen/cases/one.json": json.dumps({"id": "one", "ground_truth": {"verdict": "ACT"}}),
            }
            for name, content in files.items():
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            with self.assertRaisesRegex(BoundaryError, "production bridge references"):
                inspect_gitworthy(repo, "HEAD")


if __name__ == "__main__":
    unittest.main()
