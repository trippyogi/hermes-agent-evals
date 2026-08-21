"""Read-only verification of the GitWorthy advisory integration boundary.

The verifier inspects immutable Git objects.  It never checks out, edits, or
executes GitWorthy, so running it cannot affect GitWorthy policy or state.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


POLICY_ROOTS = (
    "src/core/worth-check.ts",
    "src/core/rank.ts",
    "src/core/scan.ts",
    "src/core/hunt.ts",
    "src/decision/policy.ts",
)
FORBIDDEN_BRIDGE_TOKENS = (
    "EvalOpportunity",
    "EvalEvidence",
    "evalability",
    "hermes-agent-evals",
    "integrations/gitworthy",
)
POST_OUTCOME_FIELDS = frozenset(
    {
        "result",
        "oracle",
        "frame_conditions",
        "candidate_sha",
        "trace_bundle_sha256",
        "platforms",
        "merged",
        "close_reason",
        "outcome_event",
    }
)
VERDICT_FIELDS = frozenset(
    {"gitworthy_verdict", "verdict", "disposition", "ranking_score", "ranking_version"}
)


class BoundaryError(RuntimeError):
    """The immutable GitWorthy boundary does not satisfy the alpha contract."""


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=False
    )
    if proc.returncode:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise BoundaryError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _blob(repo: Path, ref: str, path: str) -> bytes:
    return _git(repo, "show", f"{ref}:{path}")


def _tree_paths(repo: Path, ref: str, prefix: str) -> list[str]:
    raw = _git(repo, "ls-tree", "-r", "--name-only", ref, "--", prefix)
    return sorted(line for line in raw.decode().splitlines() if line)


def _blob_set_sha256(repo: Path, ref: str, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_blob(repo, ref, path))
        digest.update(b"\0")
    return digest.hexdigest()


def _ranking_version(source: str) -> str:
    match = re.search(r"RANKING_VERSION\s*=\s*['\"]([^'\"]+)['\"]", source)
    if not match:
        raise BoundaryError("GitWorthy RANKING_VERSION was not found")
    return match.group(1)


def _verdict_vector(repo: Path, ref: str, cases: list[str]) -> list[dict[str, Any]]:
    vector: list[dict[str, Any]] = []
    for path in cases:
        payload = json.loads(_blob(repo, ref, path))
        expected = (
            payload.get("ground_truth")
            or payload.get("expected")
            or payload.get("expect")
            or {}
        )
        verdict = expected.get("verdict")
        if verdict not in {"ACT", "VERIFY", "SKIP"}:
            raise BoundaryError(f"{path} has no frozen ACT/VERIFY/SKIP verdict")
        vector.append({"case_id": payload.get("case_id") or payload.get("id"), "verdict": verdict})
    return vector


def _production_bridge_hits(repo: Path, ref: str) -> list[str]:
    hits: list[str] = []
    for path in _tree_paths(repo, ref, "src"):
        if not path.endswith((".ts", ".tsx", ".js", ".mjs")):
            continue
        source = _blob(repo, ref, path).decode("utf-8", errors="replace")
        for token in FORBIDDEN_BRIDGE_TOKENS:
            if token.lower() in source.lower():
                hits.append(f"{path}: {token}")
    return hits


def _relative_imports(source: str) -> list[str]:
    patterns = (
        r"(?:import|export)\s+(?:[^'\"]+?\s+from\s+)?['\"](\.[^'\"]+)['\"]",
        r"import\(['\"](\.[^'\"]+)['\"]\)",
    )
    return [match for pattern in patterns for match in re.findall(pattern, source)]


def _resolve_import(current: str, target: str, known: set[str]) -> str | None:
    candidate = str(PurePosixPath(current).parent.joinpath(target))
    options = [candidate]
    if candidate.endswith(".js"):
        options.insert(0, candidate[:-3] + ".ts")
    if not PurePosixPath(candidate).suffix:
        options.extend((candidate + ".ts", candidate + "/index.ts"))
    return next((item for item in options if item in known), None)


def _policy_dependency_paths(repo: Path, ref: str) -> set[str]:
    known = set(_tree_paths(repo, ref, "src"))
    pending = [path for path in POLICY_ROOTS if path in known]
    visited: set[str] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        source = _blob(repo, ref, path).decode("utf-8", errors="replace")
        for target in _relative_imports(source):
            resolved = _resolve_import(path, target, known)
            if resolved and resolved not in visited:
                pending.append(resolved)
    return visited


def inspect_gitworthy(repo: Path, ref: str) -> dict[str, Any]:
    """Return pinned evidence, raising when the advisory boundary is crossed."""
    repo = repo.resolve()
    sha = _git(repo, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    package = json.loads(_blob(repo, sha, "package.json"))
    ranking_version = _ranking_version(_blob(repo, sha, "src/core/rank.ts").decode())
    cases = _tree_paths(repo, sha, "eval/frozen/cases")
    if not cases:
        raise BoundaryError("no frozen GitWorthy cases found")
    bridge_hits = _production_bridge_hits(repo, sha)
    if bridge_hits:
        raise BoundaryError("production bridge references found: " + "; ".join(bridge_hits))
    dependency_paths = _policy_dependency_paths(repo, sha)
    forbidden_reads = sorted(
        path
        for path in dependency_paths
        if path.endswith("track-o-covariates.ts") or "eval-opportunity" in path or "eval-evidence" in path
    )
    if forbidden_reads:
        raise BoundaryError("verdict/ranking path reaches analysis data: " + ", ".join(forbidden_reads))
    return {
        "schema": "GitWorthyAdvisoryBoundaryV1",
        "schema_version": 1,
        "gitworthy": {
            "repository": "trippyogi/gitworthy",
            "sha": sha,
            "package_version": package["version"],
            "ranking_version": ranking_version,
        },
        "frozen_eval": {
            "case_count": len(cases),
            "cases_sha256": _blob_set_sha256(repo, sha, cases),
            "verdict_vector": _verdict_vector(repo, sha, cases),
        },
        "boundary": {
            "production_bridge_references": [],
            "policy_dependency_count": len(dependency_paths),
            "policy_reads_track_o_covariates": False,
            "policy_reads_eval_evidence": False,
        },
    }


def assert_pinned_boundary(repo: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Recompute and compare all immutable evidence in a pinned manifest."""
    expected_sha = manifest["gitworthy"]["sha"]
    observed = inspect_gitworthy(repo, expected_sha)
    if observed != manifest:
        raise BoundaryError("pinned GitWorthy boundary evidence differs from manifest")
    return observed
