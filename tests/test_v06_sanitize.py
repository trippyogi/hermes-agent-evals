from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hermes_eval.corpus.sanitize import CorpusSanitizer, scan_sanitized


class V06SanitizerTests(unittest.TestCase):
    def test_nested_redaction_and_report(self):
        raw = {
            "Authorization": "Bearer super-secret-token",
            "prompt": "email me at person@example.com; read /home/alice/private/file.txt",
            "nested": [{"api_key": "sk-ant-1234567890", "env": {"TOKEN": "secret"}}],
        }
        sanitizer = CorpusSanitizer("corpus-a")
        clean = sanitizer.sanitize(raw)
        rendered = repr(clean)
        for secret in ("super-secret-token", "person@example.com", "/home/alice", "sk-ant-1234567890"):
            self.assertNotIn(secret, rendered)
        self.assertEqual(scan_sanitized(clean), [])
        report = sanitizer.report(clean, source_type_known=True, manual_spot_check=True)
        self.assertTrue(report["safe_to_commit"])
        self.assertEqual(report["fields_removed"], 1)
        self.assertEqual(report["fields_fingerprinted"], 2)

    def test_stable_within_corpus_and_isolated_across_corpora(self):
        raw = {"text": "/home/alice/a /home/alice/a", "token": "secret-value"}
        a1 = CorpusSanitizer("a").sanitize(raw)
        a2 = CorpusSanitizer("a").sanitize(raw)
        b = CorpusSanitizer("b").sanitize(raw)
        self.assertEqual(a1, a2)
        self.assertEqual(a1["text"], b["text"])
        self.assertNotEqual(a1["token"], b["token"])

    def test_idempotent(self):
        sanitizer = CorpusSanitizer("a")
        once = sanitizer.sanitize({"token": "secret-value", "text": "/home/alice/a"})
        twice = CorpusSanitizer("a").sanitize(once)
        self.assertEqual(once, twice)

    def test_fail_closed_without_known_source_and_review(self):
        sanitizer = CorpusSanitizer("a")
        clean = sanitizer.sanitize({"text": "public"})
        self.assertFalse(sanitizer.report(clean, source_type_known=False, manual_spot_check=True)["safe_to_commit"])
        self.assertFalse(sanitizer.report(clean, source_type_known=True, manual_spot_check=False)["safe_to_commit"])

    def test_residual_secret_is_detected(self):
        self.assertTrue(scan_sanitized({"text": "Bearer still-secret-value"}))


if __name__ == "__main__":
    unittest.main()
