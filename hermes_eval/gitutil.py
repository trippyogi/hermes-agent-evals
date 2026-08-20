"""Resolve Hermes refs to isolated checkouts. Portable: no workstation paths.

SUT objects come from git remotes listed in the provenance manifest
(default: github.com/NousResearch/hermes-agent). Optional local caches
and --hermes-source still work. Results always store full SHAs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_ROOT = REPO_ROOT / ".worktrees"
MANIFEST_PATH = REPO_ROOT / "evals" / "provenance" / "manifest.json"
DEFAULT_SUT_CACHE = REPO_ROOT / ".cache" / "hermes-sut"


def _load_manifest() -> dict:
    if MANIFEST_PATH.is_file():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def sut_remotes() -> list[str]:
    env = os.environ.get("HERMES_EVAL_SUT_REMOTE", "").strip()
    if env:
        return [env]
    manifest = _load_manifest()
    fetch = manifest.get("fetch") or {}
    remotes = list(fetch.get("sut_remotes") or [])
    if not remotes:
        remotes = ["https://github.com/NousResearch/hermes-agent.git"]
    return remotes


def sut_cache_dir() -> Path:
    override = os.environ.get("HERMES_EVAL_SUT_CACHE", "").strip()
    return Path(override) if override else DEFAULT_SUT_CACHE


def extra_local_sources() -> list[Path]:
    """Optional extra clones. Never required. Not recorded in the manifest."""
    raw = os.environ.get("HERMES_EVAL_SUT_SOURCES", "").strip()
    if not raw:
        return []
    return [Path(p) for p in raw.split(os.pathsep) if p.strip()]


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
    aliases = _aliases()
    if ref in aliases:
        return aliases[ref]
    return ref


def git_sha(root: Path, short: int | None = None) -> str:
    if short:
        return run_git(["rev-parse", f"--short={short}", "HEAD"], cwd=root)
    return run_git(["rev-parse", "HEAD"], cwd=root)


def harness_git_state() -> dict:
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


def discover_python() -> str:
    env = os.environ.get("HERMES_EVAL_PYTHON", "").strip()
    if env:
        return env
    return sys.executable


def _has_commit(repo: Path, sha: str) -> bool:
    git_dir = repo / ".git"
    if not git_dir.exists() and not (repo / "HEAD").exists():
        return False
    try:
        run_git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo)
        return True
    except subprocess.CalledProcessError:
        return False


def _full_sha(repo: Path, ref: str) -> str:
    return run_git(["rev-parse", ref], cwd=repo)


def _git_dir_args(cache: Path) -> list[str]:
    if (cache / "HEAD").is_file() and not (cache / ".git").exists():
        return ["--git-dir", str(cache)]
    return ["-C", str(cache)]


def ensure_sut_cache() -> Path:
    cache = sut_cache_dir()
    cache.parent.mkdir(parents=True, exist_ok=True)
    if (cache / "HEAD").exists() or (cache / ".git").exists():
        return cache
    cache.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", str(cache)],
        check=True,
        capture_output=True,
        text=True,
    )
    return cache


def _fetch_into_cache(cache: Path, remote: str, ref: str, *, depth: int | None) -> None:
    args = ["git", *_git_dir_args(cache), "fetch"]
    if depth is not None:
        args.extend([f"--depth={depth}"])
    args.extend([remote, ref])
    subprocess.run(args, check=True, capture_output=True, text=True)


def fetch_sha(sha: str, *, allow_network: bool = True) -> str:
    """Ensure ``sha`` exists in the SUT cache. Returns the full SHA."""
    sha = expand_ref(sha)
    cache = ensure_sut_cache()
    if _has_commit(cache, sha):
        return _full_sha(cache, sha)
    if not allow_network:
        raise SystemExit(
            f"SUT cache has no {sha} and fetch is disabled "
            f"(HERMES_EVAL_ALLOW_FETCH=0). Pass --hermes-source or enable fetch."
        )
    last_err = None
    for remote in sut_remotes():
        for depth in (1, None):
            try:
                _fetch_into_cache(cache, remote, sha, depth=depth)
                if _has_commit(cache, sha):
                    return _full_sha(cache, sha)
            except subprocess.CalledProcessError as exc:
                last_err = exc
                continue
    detail = ""
    if last_err is not None:
        detail = (last_err.stderr or last_err.stdout or str(last_err))[-400:]
    raise SystemExit(
        f"cannot fetch Hermes SHA {sha} from {sut_remotes()}. {detail}"
    )


def fetch_shas(shas: list[str], *, allow_network: bool = True) -> list[str]:
    return [fetch_sha(sha, allow_network=allow_network) for sha in shas]


def fetch_moving_ref(ref: str = "refs/heads/main") -> str:
    """Fetch a moving branch and return its **full SHA**. Never store the branch name."""
    cache = ensure_sut_cache()
    last_err = None
    for remote in sut_remotes():
        for depth in (1, None):
            try:
                _fetch_into_cache(cache, remote, ref, depth=depth)
                return run_git([*_git_dir_args(cache), "rev-parse", "FETCH_HEAD"])
            except subprocess.CalledProcessError as exc:
                last_err = exc
                continue
    detail = ""
    if last_err is not None:
        detail = (last_err.stderr or last_err.stdout or str(last_err))[-400:]
    raise SystemExit(f"cannot fetch {ref} from {sut_remotes()}. {detail}")


def _deepen_for_ancestry(cache: Path, descendant: str) -> None:
    """Pull more history so merge-base can see whether a SHA is on this line."""
    for remote in sut_remotes():
        try:
            subprocess.run(
                ["git", *_git_dir_args(cache), "fetch", "--deepen=256", remote],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            continue
        try:
            _fetch_into_cache(cache, remote, descendant, depth=None)
        except subprocess.CalledProcessError:
            continue


def is_ancestor(ancestor: str, descendant: str) -> bool | None:
    """True if ancestor is an ancestor of descendant. None if unknown.

    Never treat a shallow-history miss as a proven non-ancestor. False
    regression claims require a confirmed ancestor relationship.
    """
    cache = ensure_sut_cache()
    try:
        anc = fetch_sha(ancestor)
        desc = fetch_sha(descendant)
    except SystemExit:
        return None

    def _check() -> bool | None:
        proc = subprocess.run(
            ["git", *_git_dir_args(cache), "merge-base", "--is-ancestor", anc, desc],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return True
        err = (proc.stderr or proc.stdout or "").lower()
        if proc.returncode == 1 and "fatal" not in err:
            return False
        return None

    result = _check()
    if result is True:
        return True
    _deepen_for_ancestry(cache, desc)
    return _check()


def worktree_for(sha: str) -> Path:
    full = fetch_sha(sha)
    dest = WORKTREE_ROOT / full[:12]
    if dest.is_dir():
        try:
            if git_sha(dest) == full:
                return dest.resolve()
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    cache = ensure_sut_cache()
    last_err = None
    try:
        subprocess.run(
            ["git", *_git_dir_args(cache), "worktree", "add", "--detach", str(dest), full],
            check=True,
            capture_output=True,
            text=True,
        )
        return dest.resolve()
    except subprocess.CalledProcessError as exc:
        last_err = exc
        shutil.rmtree(dest, ignore_errors=True)

    # Shallow objects from --depth=1 sometimes lack trees for worktree add.
    # Re-fetch without --depth, then retry; last resort is a non-bare checkout.
    for remote in sut_remotes():
        try:
            _fetch_into_cache(cache, remote, full, depth=None)
            subprocess.run(
                ["git", *_git_dir_args(cache), "worktree", "add", "--detach", str(dest), full],
                check=True,
                capture_output=True,
                text=True,
            )
            return dest.resolve()
        except subprocess.CalledProcessError as exc:
            last_err = exc
            shutil.rmtree(dest, ignore_errors=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    for remote in sut_remotes():
        try:
            subprocess.run(
                ["git", "clone", "--no-checkout", remote, str(dest)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(dest), "fetch", "--depth=1", remote, full],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(dest), "checkout", "--detach", full],
                check=True,
                capture_output=True,
                text=True,
            )
            if git_sha(dest) == full:
                return dest.resolve()
        except subprocess.CalledProcessError as exc:
            last_err = exc
            shutil.rmtree(dest, ignore_errors=True)
    detail = ""
    if last_err is not None:
        detail = (last_err.stderr or last_err.stdout or str(last_err))[-400:]
    raise SystemExit(f"cannot materialize worktree for {full}. {detail}")


def _allow_fetch() -> bool:
    raw = os.environ.get("HERMES_EVAL_ALLOW_FETCH", "1").strip().lower()
    return raw not in {"0", "false", "no"}


def resolve_hermes_root(ref: str, source: Path | None = None) -> tuple[Path, str]:
    """Return (checkout_path, full_sha) for a Hermes ref.

    Order: explicit path, --hermes-source / HERMES_EVAL_SUT_SOURCES,
    existing matching worktree, then fetch from configured remotes into
    ``.cache/hermes-sut`` and add a detached worktree under ``.worktrees/``.
    """
    raw = expand_ref(ref)
    as_path = Path(raw)
    if as_path.is_dir() and ((as_path / ".git").exists() or (as_path / "run_agent.py").is_file()):
        return as_path.resolve(), git_sha(as_path)

    sources = [source] if source else []
    sources.extend(extra_local_sources())
    for repo in sources:
        if repo and repo.is_dir() and _has_commit(repo, raw):
            full = _full_sha(repo, raw)
            dest = WORKTREE_ROOT / full[:12]
            if dest.is_dir():
                try:
                    if git_sha(dest) == full:
                        return dest.resolve(), full
                except Exception:
                    pass
            WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
            if not dest.is_dir():
                run_git(["worktree", "add", "--detach", str(dest), full], cwd=repo)
            return dest.resolve(), full

    cached_wt = WORKTREE_ROOT / (raw[:12] if len(raw) >= 12 else raw)
    if cached_wt.is_dir():
        try:
            head = git_sha(cached_wt)
            if head == raw or head.startswith(raw) or raw.startswith(head[:12]):
                return cached_wt.resolve(), head
        except Exception:
            pass

    full = fetch_sha(raw, allow_network=_allow_fetch())
    path = worktree_for(full)
    return path, full


def historical_shas() -> list[str]:
    manifest = _load_manifest()
    shas = []
    bad = (manifest.get("known_bad") or {}).get("sha")
    if bad:
        shas.append(bad)
    for meta in (manifest.get("known_good") or {}).values():
        if isinstance(meta, dict) and meta.get("sha"):
            shas.append(meta["sha"])
    return shas


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
        "python_executable": discover_python(),
        "cwd": str(Path.cwd()),
        "manifest": "evals/provenance/manifest.json",
        "sut_cache": str(sut_cache_dir()),
        "sut_remotes": sut_remotes(),
    }
    if extra:
        payload.update(extra)
    return payload


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
