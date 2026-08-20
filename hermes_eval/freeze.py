"""Fixture file digests and freeze metadata. No workstation paths."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from hermes_eval.fixtureload import load_expected_historical, load_manifest
from hermes_eval.gitutil import REPO_ROOT, harness_git_state

FIXTURE_FILES = [
    "evals/fixtures/zero-toolset.yaml",
    "evals/fixtures/delegate-fallback-runtime.yaml",
    "evals/fixtures/stale-pin-rescope.yaml",
    "evals/fixtures/zero-toolset-live.yaml",
    "evals/fixtures/compression-prefix-probe.yaml",
    "evals/provenance/expected-historical.json",
    "evals/provenance/manifest.json",
    "evals/suites/core-failures.yaml",
]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_payload() -> dict:
    git_state = harness_git_state()
    files = []
    for rel in FIXTURE_FILES:
        path = REPO_ROOT / rel
        files.append(
            {
                "path": rel.replace("\\", "/"),
                "sha256": file_digest(path) if path.is_file() else None,
                "bytes": path.stat().st_size if path.is_file() else None,
            }
        )
    return {
        "harness_sha": git_state["harness_sha"],
        "harness_dirty": git_state["harness_dirty"],
        "v0_1_tag": "v0.1.0",
        "v0_1_sha": "0641093d26fe0fa7c91a771029dd61441a06ff6a",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "expected_historical": load_expected_historical(),
        "manifest_version": (load_manifest().get("manifest_version")),
    }


def write_freeze(path: Path | None = None) -> Path:
    dest = path or (REPO_ROOT / "evals" / "provenance" / "fixture-digests.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(freeze_payload(), indent=2) + "\n", encoding="utf-8")
    return dest
