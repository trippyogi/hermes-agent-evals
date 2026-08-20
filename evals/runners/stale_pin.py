"""Stale pin republish after profile rescope.

Drives pin / unpin / A→B→A at the store+reconcile boundary. The SUT input
is the pin atom's shipped scope policy (profile-in-key vs connection-only),
detected from layout.ts — not a unit assertion on connectionScopeSuffix().
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hermes_eval.redact import redact_obj

PIN_ATOM_RE = re.compile(
    r"export const \$pinnedSessionIds\s*=\s*connectionScopedAtom\((?P<body>.*?)\n\)",
    re.DOTALL,
)


def detect_pin_includes_profile(hermes_root: Path) -> tuple[bool, str]:
    """Observe how the product constructs the pin atom.

    True → pin copies fragment by profile (known-bad #90021).
    False → pin set is gateway-wide (known-good fix).
    """
    layout = hermes_root / "apps" / "desktop" / "src" / "store" / "layout.ts"
    scoped = hermes_root / "apps" / "desktop" / "src" / "lib" / "connection-scoped.ts"
    if not layout.is_file():
        raise SystemExit(f"no desktop layout store under {hermes_root}")

    text = layout.read_text(encoding="utf-8")
    match = PIN_ATOM_RE.search(text)
    if not match:
        # Older trees still use the atom; fall back to a tighter scan.
        idx = text.find("$pinnedSessionIds")
        body = text[idx : idx + 400] if idx >= 0 else text
    else:
        body = match.group("body")

    if re.search(r"includeProfile\s*:\s*false", body):
        return False, "pin atom sets includeProfile: false"
    if "includeProfile" in body:
        return True, "pin atom leaves includeProfile true"

    # Policy lives on the helper default when the pin atom passes no options.
    if scoped.is_file():
        helper = scoped.read_text(encoding="utf-8")
        if "includeProfile" not in helper:
            return True, "connection scope always includes profile (pre-option)"
    return True, "pin atom uses default connectionScopedAtom (profile in key)"


class PinStore:
    """Gateway pin set + backend PATCH log. Mirrors pin-sync reconcile."""

    def __init__(self, include_profile: bool, base_url: str):
        self.include_profile = include_profile
        self.base_url = base_url
        self.storage: dict[str, list[str]] = {}
        self.connection = {"mode": "remote", "baseUrl": base_url, "profile": "default"}
        self.local: list[str] = []
        self.backend: dict[str, bool] = {}
        self.patches: list[dict] = []
        self.mirrored: set[str] = set()
        self.state_writes = 0

    def _suffix(self, profile: str) -> str:
        base = quote(self.base_url, safe="")
        if not self.include_profile:
            return f".remote.{base}"
        return f".remote.{base}.{quote(profile, safe='')}"

    def _key(self, profile: str | None = None) -> str:
        prof = profile if profile is not None else self.connection["profile"]
        return "hermes.desktop.pinnedSessions" + self._suffix(prof)

    def persist(self) -> None:
        self.storage[self._key()] = list(self.local)
        self.state_writes += 1

    def _patch(self, session_id: str, pinned: bool, *, user: bool) -> None:
        self.patches.append(
            {
                "op": "patch",
                "id": session_id,
                "pinned": pinned,
                "user_action": user,
                "profile": self.connection["profile"],
            }
        )
        self.backend[session_id] = pinned
        self.state_writes += 1

    def pin(self, session_id: str, *, user: bool = True) -> None:
        if session_id not in self.local:
            self.local.append(session_id)
        self.persist()
        self._patch(session_id, True, user=user)
        self.mirrored.add(session_id)

    def unpin(self, session_id: str, *, user: bool = True) -> None:
        self.local = [item for item in self.local if item != session_id]
        self.persist()
        self._patch(session_id, False, user=user)
        self.mirrored.discard(session_id)

    def set_connection(self, profile: str) -> None:
        old_key = self._key()
        self.connection = {
            "mode": "remote",
            "baseUrl": self.base_url,
            "profile": profile,
        }
        new_key = self._key()
        if old_key != new_key:
            # Profile-scoped pin atom: suffix changed → reset mirror and reload.
            # Connection-only pin atom: suffix stable → local set unchanged.
            self.mirrored.clear()
            self.local = list(self.storage.get(new_key, []))
            self.reconcile()

    def reconcile(self) -> None:
        # After a scope reload the mirror is empty, so every local id looks
        # "new" and pin-sync re-asserts PATCH pinned=true (the #90021 flush).
        for session_id in list(self.local):
            if session_id not in self.mirrored:
                self._patch(session_id, True, user=False)
                self.mirrored.add(session_id)


def run_scenario(include_profile: bool) -> dict:
    store = PinStore(include_profile=include_profile, base_url="https://gw.example:8443")
    events: list[dict] = []

    store.set_connection("default")
    store.pin("S")
    events.append({"op": "pin", "id": "S", "profile": "default"})

    store.set_connection("k9")
    store.pin("S")
    events.append({"op": "pin", "id": "S", "profile": "k9"})

    store.set_connection("default")
    store.unpin("S")
    events.append({"op": "unpin", "id": "S", "profile": "default"})
    after_unpin = list(store.local)
    backend_after_unpin = dict(store.backend)

    store.set_connection("k9")
    events.append({"op": "rescope", "profile": "k9", "local": list(store.local)})
    store.set_connection("default")
    events.append({"op": "rescope", "profile": "default", "local": list(store.local)})

    unsolicited = [
        p
        for p in store.patches
        if p["pinned"] is True and not p["user_action"]
    ]
    # Only count re-pins after the user unpin.
    unpin_idx = next(
        i
        for i, p in enumerate(store.patches)
        if p["id"] == "S" and p["pinned"] is False and p["user_action"]
    )
    unsolicited_after_unpin = [
        p for p in store.patches[unpin_idx + 1 :] if p["pinned"] is True and not p["user_action"]
    ]
    final_unpinned = "S" not in store.local and store.backend.get("S") is not True
    return {
        "include_profile": include_profile,
        "events": events,
        "patches": store.patches,
        "unsolicited_pin_patches": len(unsolicited_after_unpin),
        "unsolicited": unsolicited_after_unpin,
        "local_final": list(store.local),
        "backend_final": dict(store.backend),
        "backend_after_unpin": backend_after_unpin,
        "after_unpin_local": after_unpin,
        "storage_keys": sorted(store.storage),
        "state_writes": store.state_writes,
        "final_unpinned": final_unpinned,
    }


def run(hermes_root: Path, hermes_sha: str, out_dir: Path) -> dict:
    started = time.perf_counter()
    include_profile, policy_note = detect_pin_includes_profile(hermes_root)
    scenario = run_scenario(include_profile)
    success = scenario["final_unpinned"] and scenario["unsolicited_pin_patches"] == 0
    notes = [policy_note]
    if success:
        notes.append("S stayed unpinned across A→B→A; no unsolicited PATCH pinned=true")
    else:
        notes.append(
            f"stale republish: unsolicited_pin_patches={scenario['unsolicited_pin_patches']} "
            f"final_unpinned={scenario['final_unpinned']}"
        )

    duration_ms = (time.perf_counter() - started) * 1000
    result = {
        "fixture": "stale-pin-rescope",
        "fixture_version": 2,
        "hermes_ref": hermes_sha,
        "model": None,
        "provider": None,
        "success": success,
        "turns": None,
        "tool_calls": 0,
        "tool_calls_success": 0,
        "tool_calls_failed": 0,
        "invalid_tool_calls": 0,
        "wasted_tool_calls": scenario["unsolicited_pin_patches"],
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "recovered": success,
        "recovery_turns": None,
        "recovery_tool_calls": None,
        "cache_prefix_stable": None,
        "duration_ms": round(duration_ms, 1),
        "notes": notes,
        "not_observable": [
            "turns",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_prefix_stable",
            "recovery_turns",
        ],
        "extras": {
            "pin_includes_profile": include_profile,
            **scenario,
        },
    }
    return redact_obj(result)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hermes-root", required=True)
    p.add_argument("--hermes-sha", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    result = run(Path(args.hermes_root), args.hermes_sha, Path(args.out))
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": result["success"], "out": args.out}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
