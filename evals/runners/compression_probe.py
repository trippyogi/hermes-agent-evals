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
from hermes_eval.wirewrap import hash_request, prefix_churn, sha16, shared_prefix_stats

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
    if getattr(agent, "tools", None) in (None, []):
        agent.tools = TOOL_DEFS
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


def _outgoing_messages(kwargs: dict, fallback: list) -> list:
    messages = kwargs.get("messages")
    if isinstance(messages, list) and messages:
        return messages
    incoming = kwargs.get("input")
    if isinstance(incoming, list) and incoming:
        return incoming
    return fallback


def _turn_row(turn: str, kwargs: dict, messages: list, t1_messages: list | None, compression: bool) -> dict:
    req = hash_request(kwargs)
    outgoing = _outgoing_messages(kwargs, messages)
    stats = shared_prefix_stats(t1_messages or outgoing, outgoing)
    return {
        "turn": turn,
        "system_hash": req.get("system_prompt_hash"),
        "tools_hash": req.get("tool_schema_hash"),
        "message_count": req.get("message_count") or len(outgoing),
        "shared_prefix_count": stats["shared_prefix_count"],
        "prefix_retention_ratio": stats["prefix_retention_ratio"],
        "compression_event": compression,
        "first_divergence": stats["first_divergence"],
        "request": req,
    }


def _drive_longitudinal(agent, records: list[dict]) -> tuple[list[str], list[dict]]:
    """Accumulate one session: T1–T4 suffix growth, T5 force compress()."""
    notes: list[str] = []
    turns: list[dict] = []
    system = agent._cached_system_prompt or "You are Hermes eval. Tools: write_file."
    messages: list[dict] = [{"role": "system", "content": system}]
    t1_messages: list | None = None

    for t in range(1, 5):
        messages.append({"role": "user", "content": f"longitudinal suffix turn {t}: ping {t}"})
        try:
            kwargs = agent._build_api_kwargs(list(messages))
        except Exception as exc:
            notes.append(f"T{t} _build_api_kwargs failed: {type(exc).__name__}")
            kwargs = {"messages": list(messages), "tools": getattr(agent, "tools", TOOL_DEFS)}
        if t == 1:
            t1_messages = list(_outgoing_messages(kwargs, messages))
        row = _turn_row(f"T{t}", kwargs, messages, t1_messages, compression=False)
        records.append({"kind": "longitudinal_turn", "compression_event": False, **row})
        turns.append(row)
        try:
            agent._interruptible_api_call(kwargs)
            notes.append(f"T{t} interruptible_api_call ok; messages={row['message_count']}")
        except Exception as exc:
            notes.append(f"T{t} interruptible_api_call: {type(exc).__name__} (hashed anyway)")
        messages.append({"role": "assistant", "content": "ok"})

    bulky = list(messages)
    for i in range(8):
        bulky.append({"role": "user", "content": f"history {i} " + ("x" * 80)})
        bulky.append({"role": "assistant", "content": f"ack {i}"})
    bulky.append({"role": "user", "content": "T5 force-compress suffix"})
    compressor = getattr(agent, "context_compressor", None)
    compressed = bulky
    saw = False
    if compressor is None:
        notes.append("T5 no context_compressor; hashing bulky payload")
    else:
        try:
            compressed = compressor.compress(bulky, current_tokens=50_000, force=True)
            saw = True
            notes.append(
                f"T5 compress() returned "
                f"{len(compressed) if isinstance(compressed, list) else type(compressed).__name__}"
            )
        except Exception as exc:
            notes.append(f"T5 compress() failed: {type(exc).__name__}; hashing bulky payload")
            compressed = bulky
    payload = compressed if isinstance(compressed, list) else bulky
    try:
        kwargs = agent._build_api_kwargs(payload)
    except Exception as exc:
        notes.append(f"T5 _build_api_kwargs failed: {type(exc).__name__}")
        kwargs = {"messages": payload, "tools": getattr(agent, "tools", TOOL_DEFS)}
    row = _turn_row("T5", kwargs, payload, t1_messages, compression=True)
    row["compress_invoked"] = saw
    records.append({"kind": "longitudinal_turn", "compression_event": True, **row})
    turns.append(row)
    return notes, turns


def run(hermes_root: Path | None, hermes_sha: str | None, out_dir: Path) -> dict:
    started = time.perf_counter()
    notes: list[str] = []
    records: list[dict] = []
    home = write_isolated_home()
    turns: list[dict] = []
    scenarios = {"longitudinal": None, "t1_t4_suffix_growth": None, "t5_force_compress": None}

    if hermes_root is None:
        notes.append("no hermes root")
        duration_ms = (time.perf_counter() - started) * 1000
        return _result(hermes_sha, notes, records, scenarios, duration_ms, success=False, turns=turns)

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
                extra, turns = _drive_longitudinal(agent, records)
                notes.extend(extra)
                scenarios["longitudinal"] = turns
                scenarios["t1_t4_suffix_growth"] = prefix_churn(
                    [r for r in records if r.get("turn") in {"T1", "T2", "T3", "T4"}]
                )
                scenarios["t5_force_compress"] = next(
                    (r for r in turns if r.get("turn") == "T5"),
                    None,
                )
            except Exception as exc:
                notes.append(f"agent probe failed: {type(exc).__name__}: {exc}")

    measurable = any(r.get("request", {}).get("system_prompt_hash") for r in records) or any(
        t.get("system_hash") for t in turns
    )
    churn = prefix_churn(records)
    success = measurable and len(turns) == 5
    duration_ms = (time.perf_counter() - started) * 1000
    return _result(hermes_sha, notes, records, scenarios, duration_ms, success, churn, turns)


def _result(hermes_sha, notes, records, scenarios, duration_ms, success, churn=None, turns=None):
    not_obs = []
    if not any(r.get("input_tokens") for r in records):
        not_obs.append("provider_native_token_counts")
    if not any(r.get("cache_read_tokens") for r in records if r.get("cache_read_tokens")):
        not_obs.append("provider_cache_read")
    table = []
    for row in turns or []:
        table.append(
            {
                "turn": row.get("turn"),
                "system_hash": row.get("system_hash"),
                "tools_hash": row.get("tools_hash"),
                "message_count": row.get("message_count"),
                "shared_prefix_count": row.get("shared_prefix_count"),
                "prefix_retention_ratio": row.get("prefix_retention_ratio"),
                "compression_event": row.get("compression_event"),
                "first_divergence": row.get("first_divergence"),
            }
        )
    return redact_obj(
        {
            "fixture": "compression-prefix-probe",
            "fixture_version": 3,
            "hermes_ref": hermes_sha,
            "model": "eval-mock",
            "provider": "synthetic-wrap",
            "success": success,
            "turns": len(table) or None,
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
                "longitudinal_turns": table,
                "session_model": "accumulating T1-T4 suffix growth; T5 force compress()",
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
