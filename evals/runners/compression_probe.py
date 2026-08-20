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


def _policy_unmeasured() -> list[dict]:
    return [
        {
            "event": "provider_fallback",
            "prefix_expected": "investigate",
            "measured": False,
            "observed": "unmeasured",
            "note": "v0.3 does not add a synthetic fallback prefix scenario",
        },
        {
            "event": "delegation",
            "prefix_expected": "separate_child_prefix",
            "measured": False,
            "observed": "unmeasured",
            "note": "child requests are a separate prefix, not a parent suffix",
        },
        {
            "event": "session_resume",
            "prefix_expected": "preserve_compatible",
            "measured": False,
            "observed": "unmeasured",
            "note": "ideally preserve a compatible prefix; not driven this pass",
        },
    ]


def _drive_policy(agent, turns: list[dict], records: list[dict]) -> tuple[list[dict], list[str]]:
    """Which events are legitimate prefix-invalidating boundaries?"""
    notes: list[str] = []
    t1 = next((t for t in turns if t.get("turn") == "T1"), None)
    t4 = next((t for t in turns if t.get("turn") == "T4"), None)
    t5 = next((t for t in turns if t.get("turn") == "T5"), None)
    rows: list[dict] = []

    def pack(event: str, expected: str, row: dict | None, *, measured: bool, observed: str, note: str) -> dict:
        payload = {
            "event": event,
            "prefix_expected": expected,
            "measured": measured,
            "observed": observed,
            "note": note,
        }
        if row:
            payload.update(
                {
                    "system_hash": row.get("system_hash"),
                    "tools_hash": row.get("tools_hash"),
                    "message_count": row.get("message_count"),
                    "shared_prefix_count": row.get("shared_prefix_count"),
                    "prefix_retention_ratio": row.get("prefix_retention_ratio"),
                    "first_divergence": row.get("first_divergence"),
                    "compression_event": row.get("compression_event"),
                }
            )
        return payload

    if t1 and t4:
        stable = t1.get("system_hash") == t4.get("system_hash") and t1.get("tools_hash") == t4.get("tools_hash") and t4.get("prefix_retention_ratio") == 1.0
        rows.append(
            pack(
                "ordinary_suffix_turn",
                "stable",
                t4,
                measured=True,
                observed="stable" if stable else "unexpected_change",
                note="T1–T4 accumulating suffix; cache-eligible prefix ≠ provider cache hit",
            )
        )
    else:
        rows.append(pack("ordinary_suffix_turn", "stable", None, measured=False, observed="unmeasured", note="T1/T4 missing"))

    t1_messages = [{"role": "system", "content": agent._cached_system_prompt or "You are Hermes eval. Tools: write_file."}]
    t1_messages.append({"role": "user", "content": "longitudinal suffix turn 1: ping 1"})
    t1_messages.append({"role": "assistant", "content": "ok"})
    try:
        t1_kwargs = agent._build_api_kwargs(list(t1_messages))
        t1_out = _outgoing_messages(t1_kwargs, t1_messages)
    except Exception as exc:
        notes.append(f"policy T1 rebuild failed: {type(exc).__name__}")
        t1_out = list(t1_messages)
        t1_kwargs = {"messages": t1_out, "tools": getattr(agent, "tools", TOOL_DEFS)}

    tool_msgs = list(t1_out) + [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_eval_1",
                    "type": "function",
                    "function": {"name": "write_file", "arguments": "{\"path\": \"x\"}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_eval_1", "content": "wrote x"},
        {"role": "user", "content": "continue after tool result"},
    ]
    try:
        kwargs = agent._build_api_kwargs(tool_msgs)
    except Exception as exc:
        notes.append(f"tool_result_append build failed: {type(exc).__name__}")
        kwargs = {"messages": tool_msgs, "tools": getattr(agent, "tools", TOOL_DEFS)}
    tool_row = _turn_row("tool_result_append", kwargs, tool_msgs, t1_out, compression=False)
    records.append({"kind": "policy_turn", **tool_row})
    stable_tool = tool_row.get("prefix_retention_ratio") == 1.0
    rows.append(
        pack(
            "tool_result_append",
            "stable",
            tool_row,
            measured=True,
            observed="stable" if stable_tool else "unexpected_change",
            note="tool call/result is a suffix; previous prefix should remain",
        )
    )

    orig_sys = getattr(agent, "_cached_system_prompt", None)
    agent._cached_system_prompt = str(orig_sys or "") + "\n# config changed"
    sys_msgs = [{"role": "system", "content": agent._cached_system_prompt}, {"role": "user", "content": "after system change"}]
    try:
        kwargs = agent._build_api_kwargs(sys_msgs)
    except Exception as exc:
        notes.append(f"system_change build failed: {type(exc).__name__}")
        kwargs = {"messages": sys_msgs, "tools": getattr(agent, "tools", TOOL_DEFS)}
    sys_row = _turn_row("system_change", kwargs, sys_msgs, t1_out, compression=False)
    records.append({"kind": "policy_turn", **sys_row})
    changed_sys = sys_row.get("system_hash") != (t1 or {}).get("system_hash")
    rows.append(
        pack(
            "system_prompt_config_change",
            "change",
            sys_row,
            measured=True,
            observed="change" if changed_sys else "unexpected_stable",
            note="system prompt / config change is a legitimate prefix-invalidating boundary",
        )
    )
    agent._cached_system_prompt = orig_sys

    orig_tools = list(getattr(agent, "tools", []) or [])
    extra_tool = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
    agent.tools = orig_tools + [extra_tool]
    try:
        kwargs = agent._build_api_kwargs(list(t1_messages))
    except Exception as exc:
        notes.append(f"tool_schema_change build failed: {type(exc).__name__}")
        kwargs = {"messages": t1_messages, "tools": agent.tools}
    schema_row = _turn_row("tool_schema_change", kwargs, t1_messages, t1_out, compression=False)
    records.append({"kind": "policy_turn", **schema_row})
    changed_tools = schema_row.get("tools_hash") != (t1 or {}).get("tools_hash")
    rows.append(
        pack(
            "tool_schema_change",
            "change",
            schema_row,
            measured=True,
            observed="change" if changed_tools else "unexpected_stable",
            note="tool schema change is a legitimate prefix-invalidating boundary",
        )
    )
    agent.tools = orig_tools

    if t5:
        changed = bool(t5.get("compression_event")) and t5.get("prefix_retention_ratio") == 0.0
        rows.append(
            pack(
                "compression",
                "change",
                t5,
                measured=True,
                observed="change" if changed else "unexpected_stable",
                note="compress() is an intentional prefix-invalidating boundary",
            )
        )
    rows.extend(_policy_unmeasured())
    return rows, notes


def run(hermes_root: Path | None, hermes_sha: str | None, out_dir: Path) -> dict:
    started = time.perf_counter()
    notes: list[str] = []
    records: list[dict] = []
    home = write_isolated_home()
    turns: list[dict] = []
    scenarios = {
        "longitudinal": None,
        "t1_t4_suffix_growth": None,
        "t5_force_compress": None,
        "prefix_policy": [],
    }

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
                policy, policy_notes = _drive_policy(agent, turns, records)
                notes.extend(policy_notes)
                scenarios["longitudinal"] = turns
                scenarios["prefix_policy"] = policy
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
                "prefix_policy": (scenarios or {}).get("prefix_policy") or [],
                "session_model": "accumulating T1-T4 suffix growth; T5 force compress(); policy events after",
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
