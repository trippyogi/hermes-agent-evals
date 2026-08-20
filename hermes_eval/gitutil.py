"""Resolve Hermes refs to isolated checkouts. Never write to GitHub.

Results always store immutable full SHAs. Moving labels (origin/main,
branch names) are expanded via evals/provenance/manifest.json.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_ROOT = REPO_ROOT / ".worktrees"
MANIFEST_PATH = REPO_ROOT / "evals" / "provenance" / "manifest.json"

KNOWN_SOURCE_REPOS = [
    Path(r"c:\dev\hermes-agent-wt-90009-author-fix"),
    Path(r"c:\dev\hermes-agent-wt-salvage-empty-toolsets"),
    Path(r"c:\dev\hermes-agent-wt-fix-pin-connection-scope"),
    Path(r"c:\dev\hermes-agent"),
]


def _load_manifest() -> dict:
    if MANIFEST_PATH.is_file():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def _aliases() -> dict[str, str]:
    manifest = _load_manifest()
    aliases = dict(manifest.get("aliases_do_not_use_in_results") or {})
    known_good = manifest.get("known_good") or {}
    known_bad = manifest.get("known_bad") or {}
    if known_bad.get("sha"):
        aliases.setdefault("known-bad-main", known_bad["sha"])
    for key, meta in known_good.items():
        if isinstance(meta, dict) and meta.get("sha"):
            aliases.setdefault(key, meta["sha"])
    return aliases


def _known_worktrees() -> dict[str, Path]:
    manifest = _load_manifest()
    mapping: dict[str, Path] = {}
    for meta in (manifest.get("known_good") or {}).values():
        if not isinstance(meta, dict):
            continue
        sha = meta.get("sha")
        wt = meta.get("worktree")
        if sha and wt:
            mapping[sha] = Path(wt)
            mapping[sha[:10]] = Path(wt)
        prior = meta.get("prior_sha")
        if prior and wt:
            # Prior SHA is not necessarily HEAD of that worktree; do not map it
            # to the worktree path unless it matches. Keep object lookup via git.
            pass
    bad = (manifest.get("known_bad") or {}).get("sha")
    if bad:
        mapping[bad] = WORKTREE_ROOT / bad[:12]
        mapping[bad[:10]] = WORKTREE_ROOT / bad[:12]
    return mapping


def run_git(args: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def expand_ref(ref: str) -> str:
    """Map a convenience alias to an immutable full SHA. Identity otherwise."""
    aliases = _aliases()
    if ref in aliases:
        return aliases[ref]
    return ref


def git_sha(root: Path, short: int | None = None) -> str:
    if short:
        return run_git(["rev-parse", f"--short={short}", "HEAD"], cwd=root)
    return run_git(["rev-parse", "HEAD"], cwd=root)


def harness_git_state() -> dict:
    """Return harness SHA plus dirty flag. Never invent a SHA."""
    try:
        sha = git_sha(REPO_ROOT)
    except Exception:
        return {"harness_sha": None, "harness_dirty": None, "harness_git": False}
    dirty = False
    try:
        status = run_git(["status", "--porcelain"], cwd=REPO_ROOT)
        dirty = bool(status.strip())
    except Exception:
        dirty = None  # type: ignore[assignment]
    return {"harness_sha": sha, "harness_dirty": dirty, "harness_git": True}


def harness_sha() -> str | None:
    return harness_git_state()["harness_sha"]


def _has_commit(repo: Path, sha: str) -> bool:
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        return False
    try:
        run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo)
        return True
    except subprocess.CalledProcessError:
        return False


def _full_sha(repo: Path, ref: str) -> str:
    return run_git(["rev-parse", ref], cwd=repo)


def find_existing_worktree(sha: str) -> Path | None:
    known = _known_worktrees()
    if sha in known and known[sha].is_dir():
        path = known[sha]
        try:
            head = git_sha(path)
            if head == sha or head.startswith(sha) or sha.startswith(head[:10]):
                return path
        except Exception:
            pass
        # Worktree exists but HEAD may differ (replay). Only reuse if HEAD matches.
        try:
            if git_sha(path) == sha:
                return path
        except Exception:
            return None
        return None
    for repo in KNOWN_SOURCE_REPOS:
        if not repo.is_dir():
            continue
        try:
            head = git_sha(repo)
            if head == sha or (len(sha) >= 10 and head.startswith(sha)):
                return repo
        except Exception:
            continue
    return None


def resolve_hermes_root(ref: str, source: Path | None = None) -> tuple[Path, str]:
    """Return (checkout_path, full_sha) for a Hermes ref.

    Uses an existing worktree when it already matches. Otherwise creates a
    detached worktree under this repo's ``.worktrees/`` from a local source
    that already has the object. No network, no GitHub writes.
    """
    raw = expand_ref(ref)
    as_path = Path(raw)
    if as_path.is_dir() and ((as_path / ".git").exists() or (as_path / "run_agent.py").is_file()):
        return as_path.resolve(), git_sha(as_path)

    existing = find_existing_worktree(raw)
    if existing is not None:
        return existing.resolve(), git_sha(existing)

    sources = [source] if source else []
    sources.extend(KNOWN_SOURCE_REPOS)
    repo = next((p for p in sources if p and p.is_dir() and _has_commit(p, raw)), None)
    if repo is None:
        raise SystemExit(
            f"cannot resolve Hermes ref {ref!r}: no local clone has that commit. "
            f"Pass --hermes-source pointing at a repo that contains it."
        )

    full = _full_sha(repo, raw)
    cached = find_existing_worktree(full) or find_existing_worktree(full[:10])
    if cached is not None:
        return cached.resolve(), full

    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    dest = WORKTREE_ROOT / full[:12]
    if dest.is_dir():
        try:
            if git_sha(dest) == full:
                return dest.resolve(), full
        except Exception:
            pass
        return dest.resolve(), full
    run_git(["worktree", "add", "--detach", str(dest), full], cwd=repo)
    return dest.resolve(), full


def provenance(
    hermes_root: Path,
    hermes_sha: str,
    extra: dict | None = None,
) -> dict:
    git_state = harness_git_state()
    payload = {
        "hermes_sha": hermes_sha,
        "hermes_root": str(hermes_root),
        "harness_sha": git_state["harness_sha"],
        "harness_dirty": git_state["harness_dirty"],
        "fixture_schema_version": extra.get("fixture_schema_version") if extra else None,
        "os": os.name,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cwd": str(Path.cwd()),
        "manifest": str(MANIFEST_PATH),
    }
    if extra:
        payload.update(extra)
    return payload


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
