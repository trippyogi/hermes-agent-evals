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
        self.assertNotEqual(a1["text"], b["text"])
        self.assertNotEqual(a1["token"], b["token"])

    def test_stable_across_chunk_order_and_fresh_instances(self):
        first = CorpusSanitizer("a").sanitize({"text": "/srv/private/a"})["text"]
        sanitizer = CorpusSanitizer("a")
        sanitizer.sanitize({"text": "/tmp/unrelated"})
        later = sanitizer.sanitize({"text": "/srv/private/a"})["text"]
        self.assertEqual(first, later)

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

    def test_absolute_paths_inline_env_and_cookie_are_redacted(self):
        raw = {
            "text": "read /srv/private/file and /tmp/a; Cookie: sessionid=abcdefghi",
            "environment_variables": ["OPENAI_API_KEY=abcdefghijk", "HOME=/home/alice"],
            "windows": r"C:\\Users\\alice\\private.txt",
        }
        sanitizer = CorpusSanitizer("corpus-a")
        clean = sanitizer.sanitize(raw)
        rendered = repr(clean)
        for secret in ("/srv/private/file", "/tmp/a", "sessionid=abcdefghi", "abcdefghijk", "/home/alice", "alice\\\\private"):
            self.assertNotIn(secret, rendered)
        self.assertEqual(scan_sanitized(clean), [])
        self.assertTrue(sanitizer.report(clean, source_type_known=True, manual_spot_check=True)["safe_to_commit"])


if __name__ == "__main__":
    unittest.main()
