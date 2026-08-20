"""Wire-prefix probe: wrap the outgoing request path. No Hermes core edits."""

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
from hermes_eval.redact import redact_obj
from hermes_eval.wirewrap import hash_request, prefix_churn, sha16

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "write a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
]


def _mock_response(content="ok"):
    msg = SimpleNamespace(content=content, tool_calls=None, role="assistant")
    choice = SimpleNamespace(message=msg, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=8,
        total_tokens=128,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    return SimpleNamespace(choices=[choice], usage=usage, model="eval/mock")


def _make_agent(hermes_root: Path):
    from run_agent import AIAgent

    kwargs = dict(
        api_key="eval-not-a-secret",
        base_url="http://127.0.0.1:9/v1",
        provider="openrouter",
        model="eval-mock",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    with patch("run_agent.get_tool_definitions", return_value=TOOL_DEFS), patch(
        "run_agent.check_toolset_requirements", return_value={}
    ), patch("run_agent.OpenAI"):
        try:
            agent = AIAgent(**kwargs)
        except TypeError:
            kwargs.pop("skip_memory", None)
            kwargs.pop("skip_context_files", None)
            agent = AIAgent(**kwargs)
    agent.client = MagicMock()
    agent.client.chat.completions.create.return_value = _mock_response()
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._use_prompt_caching = False
    agent._cached_system_prompt = "You are Hermes eval. Tools: write_file."
    return agent


def _wrap_agent(agent, records: list[dict]):
    orig_build = agent._build_api_kwargs
    orig_call = agent._interruptible_api_call
    orig_compress = None
    compressor = getattr(agent, "context_compressor", None)
    if compressor is not None and hasattr(compressor, "compress"):
        orig_compress = compressor.compress

    def build(messages):
        kwargs = orig_build(messages)
        records.append(
            {
                "kind": "build_api_kwargs",
                "request": hash_request(kwargs),
                "compression_event": False,
            }
        )
        return kwargs

    def call(api_kwargs):
        rec = {
            "kind": "interruptible_api_call",
            "request": hash_request(api_kwargs),
            "compression_event": False,
        }
        usage = {
            "input_tokens": 120,
            "output_tokens": 8,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        rec.update(usage)
        records.append(rec)
        return orig_call(api_kwargs)

    def compress(messages, *args, **kwargs):
        before = sha16([m.get("role") for m in messages] if isinstance(messages, list) else messages)
        out = orig_compress(messages, *args, **kwargs)
        records.append(
            {
                "kind": "compress",
                "compression_event": True,
                "before_shape": before,
                "after_count": len(out) if isinstance(out, list) else None,
                "request": hash_request({"messages": out if isinstance(out, list) else []}),
            }
        )
        return out

    agent._build_api_kwargs = build
    agent._interruptible_api_call = call
    if orig_compress is not None:
        compressor.compress = compress
    return orig_build, orig_call, orig_compress


def _drive_turns(agent, n: int, prefix: str) -> list[str]:
    notes = []
    for i in range(n):
        try:
            with patch.object(agent, "_persist_session"), patch.object(
                agent, "_save_trajectory", create=True
            ), patch.object(agent, "_cleanup_task_resources", create=True):
                agent.run_conversation(f"{prefix} turn {i+1}: ping")
            notes.append(f"run_conversation turn {i+1} ok")
        except Exception as exc:
            notes.append(f"run_conversation turn {i+1} failed: {type(exc).__name__}")
            # Fall back: still hash the payload Hermes would send.
            history = [
                {"role": "system", "content": agent._cached_system_prompt},
                {"role": "user", "content": f"{prefix} turn 1: ping"},
            ]
            for j in range(i):
                history.append({"role": "assistant", "content": "ok"})
                history.append({"role": "user", "content": f"{prefix} turn {j+2}: ping"})
            try:
                agent._build_api_kwargs(history)
                notes.append(f"fallback _build_api_kwargs turn {i+1} hashed")
            except Exception as exc2:
                notes.append(f"fallback hash failed: {type(exc2).__name__}")
    return notes


def _compression_boundary(agent, records: list[dict]) -> list[str]:
    notes = []
    compressor = getattr(agent, "context_compressor", None)
    bulky = [{"role": "system", "content": agent._cached_system_prompt or "sys"}]
    for i in range(12):
        bulky.append({"role": "user", "content": f"history {i} " + ("x" * 80)})
        bulky.append({"role": "assistant", "content": f"ack {i}"})
    bulky.append({"role": "user", "content": "suffix-only after history"})
    if compressor is None:
        notes.append("no context_compressor on agent")
        try:
            agent._build_api_kwargs(bulky)
            notes.append("hashed bulky payload without compress()")
        except Exception as exc:
            notes.append(f"bulky hash failed: {type(exc).__name__}")
        return notes
    try:
        compressed = compressor.compress(bulky, current_tokens=50_000, force=True)
        notes.append(
            f"compress() returned {len(compressed) if isinstance(compressed, list) else type(compressed).__name__}"
        )
        agent._build_api_kwargs(compressed if isinstance(compressed, list) else bulky)
        records.append(
            {
                "kind": "post_compress_build",
                "compression_event": True,
                "request": hash_request(
                    {"messages": compressed if isinstance(compressed, list) else bulky}
                ),
            }
        )
    except Exception as exc:
        notes.append(f"compress() failed: {type(exc).__name__}")
        try:
            agent._build_api_kwargs(bulky)
            notes.append("hashed bulky payload after compress failure")
        except Exception as exc2:
            notes.append(f"bulky hash failed: {type(exc2).__name__}")
    return notes


def run(hermes_root: Path | None, hermes_sha: str | None, out_dir: Path) -> dict:
    started = time.perf_counter()
    notes: list[str] = []
    records: list[dict] = []
    home = write_isolated_home()
    scenarios = {"multi_turn": None, "suffix_growth": None, "compression_boundary": None}

    if hermes_root is None:
        notes.append("no hermes root")
        duration_ms = (time.perf_counter() - started) * 1000
        return _result(hermes_sha, notes, records, scenarios, duration_ms, success=False)

    sys.path.insert(0, str(hermes_root))
    with isolated_env(home):
        with patch("run_agent.get_tool_definitions", return_value=TOOL_DEFS), patch(
            "run_agent.check_toolset_requirements", return_value={}
        ), patch("run_agent.OpenAI"), patch(
            "agent.context_compressor.get_model_context_length",
            return_value=200_000,
        ):
            try:
                agent = _make_agent(hermes_root)
                _wrap_agent(agent, records)
                notes.extend(_drive_turns(agent, 3, "stable"))
                scenarios["multi_turn"] = prefix_churn(
                    [r for r in records if r.get("kind") in {"interruptible_api_call", "build_api_kwargs"}]
                )
                before_suffix = len(records)
                notes.extend(_drive_turns(agent, 1, "suffix-only"))
                scenarios["suffix_growth"] = prefix_churn(records[before_suffix:])
                before_compress = len(records)
                notes.extend(_compression_boundary(agent, records))
                scenarios["compression_boundary"] = {
                    "records_added": len(records) - before_compress,
                    "saw_compress": any(r.get("kind") == "compress" for r in records[before_compress:]),
                }
            except Exception as exc:
                notes.append(f"agent probe failed: {type(exc).__name__}: {exc}")

    measurable = any(r.get("request", {}).get("system_prompt_hash") for r in records)
    churn = prefix_churn(records)
    success = measurable
    duration_ms = (time.perf_counter() - started) * 1000
    return _result(hermes_sha, notes, records, scenarios, duration_ms, success, churn)


def _result(hermes_sha, notes, records, scenarios, duration_ms, success, churn=None):
    not_obs = []
    if not any(r.get("input_tokens") for r in records):
        not_obs.append("provider_native_token_counts")
    if not any(r.get("cache_read_tokens") for r in records if r.get("cache_read_tokens")):
        not_obs.append("provider_cache_read")
    return redact_obj(
        {
            "fixture": "compression-prefix-probe",
            "fixture_version": 2,
            "hermes_ref": hermes_sha,
            "model": "eval-mock",
            "provider": "synthetic-wrap",
            "success": success,
            "turns": sum(1 for r in records if r.get("kind") == "interruptible_api_call") or None,
            "tool_calls": 0,
            "tool_calls_success": 0,
            "tool_calls_failed": 0,
            "invalid_tool_calls": 0,
            "wasted_tool_calls": 0,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "recovered": None,
            "cache_prefix_stable": (churn or {}).get("stable") if churn else None,
            "duration_ms": round(duration_ms, 1),
            "notes": notes,
            "not_observable": not_obs,
            "extras": {
                "records": records,
                "scenarios": scenarios,
                "prefix_churn": churn,
                "measurable_on_wire_wrap": success,
            },
        }
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hermes-root")
    p.add_argument("--hermes-sha")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    root = Path(args.hermes_root) if args.hermes_root else None
    result = run(root, args.hermes_sha, Path(args.out))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": result["success"], "out": args.out}))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
