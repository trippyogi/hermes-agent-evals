"""#90009: parent fallback then delegate — observe child runtime identity.

Synthetic endpoints only. Artifacts store credential class + fingerprint.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hermes_eval.isolate import isolated_env, write_isolated_home
from hermes_eval.redact import credential_class, credential_fingerprint, redact_obj

CODEX_BASE = "https://chatgpt.com/backend-api/codex"
ANTHROPIC_BASE = "https://api.anthropic.com"
CODEX_KEY = "codex-primary-key-0001"
ANTHROPIC_KEY = "sk-ant-oat01-fallback-token"


def _identity(provider, model, base_url, api_key, api_mode) -> dict:
    return {
        "provider": provider,
        "model": model,
        "base_url": str(base_url).rstrip("/") if base_url else None,
        "api_mode": api_mode,
        "credential_class": credential_class(api_key),
        "credential_fp": credential_fingerprint(api_key),
    }


def _coherent(identity: dict, expected: dict) -> bool:
    fields = ("provider", "model", "base_url", "api_mode", "credential_class")
    return all(identity.get(k) == expected.get(k) for k in fields)


def _auth_mismatch(child: dict, expected: dict) -> bool:
    """Child would 401 if endpoint and credential class disagree."""
    if not child.get("base_url") or not expected.get("base_url"):
        return True
    host_ok = str(child["base_url"]).rstrip("/") == str(expected["base_url"]).rstrip("/")
    cred_ok = child.get("credential_class") == expected.get("credential_class")
    mode_ok = child.get("api_mode") == expected.get("api_mode")
    return not (host_ok and cred_ok and mode_ok)


def _make_parent():
    from run_agent import AIAgent

    kwargs = dict(
        api_key=CODEX_KEY,
        base_url=CODEX_BASE,
        provider="openai-codex",
        model="gpt-5.6-sol",
        api_mode="codex_responses",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        fallback_model={"provider": "anthropic", "model": "claude-sonnet-5"},
    )
    try:
        agent = AIAgent(**kwargs)
    except TypeError:
        kwargs.pop("skip_memory", None)
        kwargs.pop("skip_context_files", None)
        try:
            agent = AIAgent(**kwargs)
        except TypeError:
            kwargs.pop("quiet_mode", None)
            agent = AIAgent(**kwargs)
    agent.client = MagicMock()
    agent.client.base_url = CODEX_BASE
    agent.client.api_key = CODEX_KEY
    return agent


def _activate_fallback(agent) -> bool:
    mock_client = MagicMock()
    mock_client.base_url = ANTHROPIC_BASE
    mock_client.api_key = ANTHROPIC_KEY
    patches = [
        patch(
            "agent.auxiliary_client.resolve_provider_client",
            return_value=(mock_client, "claude-sonnet-5"),
        )
    ]
    try:
        patches.append(
            patch("agent.anthropic_adapter.build_anthropic_client", return_value=MagicMock())
        )
    except Exception:
        pass
    entered = []
    try:
        for p in patches:
            p.start()
            entered.append(p)
        fn = getattr(agent, "_try_activate_fallback", None)
        if fn is None:
            return False
        return bool(fn())
    finally:
        for p in entered:
            p.stop()


def _desync_surface_to_primary(parent) -> None:
    """Reproduce the #90009 split-brain: live anthropic pair, stale Codex surface.

    Production fallback can update api_mode / _anthropic_* while
    provider / base_url / api_key / _client_kwargs still describe P.
    The fixture injects that state after a real fallback activation.
    """
    parent.provider = "anthropic"
    parent.model = "claude-sonnet-5"
    parent.api_mode = "anthropic_messages"
    parent._anthropic_base_url = ANTHROPIC_BASE
    parent._anthropic_api_key = ANTHROPIC_KEY
    # Stale OpenAI surface — the #90009 inherit path reads these on pre-fix.
    parent.base_url = CODEX_BASE
    parent.api_key = CODEX_KEY
    parent._client_kwargs = {"api_key": CODEX_KEY, "base_url": CODEX_BASE}
    if getattr(parent, "client", None) is not None:
        parent.client.base_url = CODEX_BASE
        parent.client.api_key = CODEX_KEY


def _build_child(parent):
    from tools.delegate_tool import _build_child_agent

    captured: dict = {}

    def _construct(*args, **kwargs):
        captured["kwargs"] = kwargs
        child = SimpleNamespace(**kwargs)
        child.provider = kwargs.get("provider")
        child.model = kwargs.get("model")
        child.base_url = kwargs.get("base_url")
        child.api_key = kwargs.get("api_key")
        child.api_mode = kwargs.get("api_mode")
        child._client_kwargs = {
            "api_key": kwargs.get("api_key"),
            "base_url": kwargs.get("base_url"),
        }
        captured["child"] = child
        return child

    with patch("run_agent.get_tool_definitions", return_value=[]), patch(
        "run_agent.check_toolset_requirements", return_value={}
    ), patch("run_agent.AIAgent", side_effect=_construct):
        _build_child_agent(
            task_index=0,
            goal="write proof that the child runtime is coherent",
            context=None,
            toolsets=None,
            model=None,
            max_iterations=5,
            parent_agent=parent,
            task_count=1,
        )
    return captured


def run(hermes_root: Path, hermes_sha: str, out_dir: Path) -> dict:
    started = time.perf_counter()
    home = write_isolated_home()
    notes: list[str] = []
    sys.path.insert(0, str(hermes_root))

    expected = _identity(
        "anthropic",
        "claude-sonnet-5",
        ANTHROPIC_BASE,
        ANTHROPIC_KEY,
        "anthropic_messages",
    )
    child_id = None
    parent_after = None
    fail_closed = False
    fail_closed_msg = None
    fallback_ok = False
    child_built = False
    wasted = 0
    turns = 2

    with isolated_env(home):
        with patch("run_agent.get_tool_definitions", return_value=[]), patch(
            "run_agent.check_toolset_requirements", return_value={}
        ), patch("run_agent.OpenAI"), patch(
            "agent.context_compressor.get_model_context_length",
            return_value=200_000,
        ):
            try:
                parent = _make_parent()
            except Exception as exc:
                notes.append(f"parent construct failed: {type(exc).__name__}")
                parent = None

            if parent is not None:
                try:
                    fallback_ok = _activate_fallback(parent)
                except Exception as exc:
                    notes.append(f"fallback failed: {type(exc).__name__}")
                    fallback_ok = False
                parent_after = _identity(
                    getattr(parent, "provider", None),
                    getattr(parent, "model", None),
                    getattr(parent, "base_url", None),
                    getattr(parent, "api_key", None)
                    or getattr(parent, "_anthropic_api_key", None),
                    getattr(parent, "api_mode", None),
                )
                if fallback_ok:
                    _desync_surface_to_primary(parent)
                    notes.append(
                        "FAULT-INJECTED #90009 split-brain: anthropic pair + stale Codex "
                        "surface. Clean fallback on the historical SHA does not naturally "
                        "produce this discriminator."
                    )
                try:
                    captured = _build_child(parent)
                    kwargs = captured.get("kwargs") or {}
                    child_id = _identity(
                        kwargs.get("provider"),
                        kwargs.get("model"),
                        kwargs.get("base_url"),
                        kwargs.get("api_key"),
                        kwargs.get("api_mode"),
                    )
                    child_built = True
                except ValueError as exc:
                    fail_closed = "cannot delegate" in str(exc).lower()
                    fail_closed_msg = "cannot delegate (details redacted)"
                    notes.append("child spawn fail-closed")
                except Exception as exc:
                    notes.append(f"child spawn error: {type(exc).__name__}")

    runtime_coherent = bool(child_id and _coherent(child_id, expected))
    auth_failures = 1 if (child_id and _auth_mismatch(child_id, expected)) else 0
    if child_id is None and not fail_closed:
        auth_failures = 1
    if child_id is None and fail_closed:
        # Fail-closed on unpaired parent is correct for the corrupted case,
        # but this fixture expects a coherent child after a real fallback.
        auth_failures = 1
        notes.append("fail-closed instead of inheriting fallback F")
    if not fallback_ok:
        notes.append("parent did not activate fallback")
        wasted += 1
    if child_built and not runtime_coherent:
        notes.append("child runtime does not match fallback F")
        wasted += 1
    if runtime_coherent:
        notes.append("child inherited complete fallback runtime F")

    success = bool(fallback_ok and runtime_coherent and auth_failures == 0)
    duration_ms = (time.perf_counter() - started) * 1000
    result = {
        "fixture": "delegate-fallback-runtime",
        "fixture_version": 2,
        "hermes_ref": hermes_sha,
        "model": "synthetic-fallback-pair",
        "provider": "synthetic",
        "success": success,
        "turns": turns,
        "tool_calls": 1 if child_built or fail_closed else 0,
        "tool_calls_success": 1 if success else 0,
        "tool_calls_failed": 0 if success else 1,
        "invalid_tool_calls": 0 if runtime_coherent else 1,
        "wasted_tool_calls": wasted,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "recovered": runtime_coherent,
        "recovery_turns": 1 if fallback_ok else None,
        "recovery_tool_calls": 1 if child_built else 0,
        "cache_prefix_stable": None,
        "duration_ms": round(duration_ms, 1),
        "notes": notes,
        "not_observable": ["input_tokens", "output_tokens", "total_tokens", "cache_prefix_stable"],
        "extras": {
            "fallback_activated": fallback_ok,
            "child_built": child_built,
            "fail_closed": fail_closed,
            "fail_closed_reason": fail_closed_msg,
            "runtime_coherent": runtime_coherent,
            "auth_failures": auth_failures,
            "expected_child": expected,
            "parent_after_fallback": parent_after,
            "child_runtime": child_id,
            "hermes_home": str(home),
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
