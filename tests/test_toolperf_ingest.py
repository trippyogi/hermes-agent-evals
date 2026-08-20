"""Toolperf ingest helpers. No live model spend; no Nous writes."""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evals.runners.wasted_turns import render_label_sheet
from hermes_eval.toolperf_ingest import ensure_extracted, sha256_file


class ToolperfIngestTests(unittest.TestCase):
    def test_label_sheet_keeps_full_source_path(self):
        source = "qwen/qwen3-coder-30b-a3b-instruct/fixes/20260806-abcdef123456"
        sheet = render_label_sheet(
            {
                "REAL_ATOF_DATA": "available",
                "corpus": "toolperf",
                "detector_hits": 1,
                "episode_count": 1,
                "overlaps_collapsed": 0,
                "by_w_label": {"W6": 1},
                "episodes": [
                    {
                        "w_labels": ["W6"],
                        "tool": "terminal",
                        "source": source,
                        "index": 0,
                        "hit_count": 1,
                        "state_changed": False,
                        "evidence": "xml",
                    }
                ],
            }
        )
        self.assertIn(source, sheet)
        self.assertIn("`qwen/qwen3-coder-30b-a3b-instruct/fixes/", sheet)

    def test_ensure_extracted_invalidates_stale_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rerun = tmp_path / "rerun"
            rerun.mkdir()
            cache = tmp_path / "cache"
            self._write_tgz(rerun / "atof-traces.tgz", "first.atof.jsonl", b'{"kind":"a"}\n')
            with patch("hermes_eval.toolperf_ingest.cache_dir", return_value=cache):
                first = ensure_extracted(rerun)
                self.assertTrue((first / "results" / "first.atof.jsonl").is_file())
                stamp = (first / "archive.sha256").read_text(encoding="utf-8").strip()
                self.assertEqual(stamp, sha256_file(rerun / "atof-traces.tgz"))
                sentinel = first / "sentinel.txt"
                sentinel.write_text("keep", encoding="utf-8")
                ensure_extracted(rerun)
                self.assertTrue(sentinel.is_file())
                self._write_tgz(rerun / "atof-traces.tgz", "second.atof.jsonl", b'{"kind":"b"}\n')
                second = ensure_extracted(rerun)
                self.assertFalse((second / "results" / "first.atof.jsonl").exists())
                self.assertTrue((second / "results" / "second.atof.jsonl").is_file())
                self.assertFalse(sentinel.exists())
                self.assertEqual(
                    (second / "archive.sha256").read_text(encoding="utf-8").strip(),
                    sha256_file(rerun / "atof-traces.tgz"),
                )

    @staticmethod
    def _write_tgz(path: Path, inner: str, body: bytes) -> None:
        with tarfile.open(path, "w:gz") as tf:
            info = tarfile.TarInfo(name=f"results/{inner}")
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))


if __name__ == "__main__":
    unittest.main()
