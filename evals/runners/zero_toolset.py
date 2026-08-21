"""Zero-toolset fixture: control (normal toolset) vs fault (cli: []).

Runs inside an isolated HERMES_HOME. A deterministic fake model either
emits a structured write_file call (when schemas exist) or dumps the same
call as assistant text (when Hermes exposed zero tools).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hermes_eval.isolate import applied_isolated_env, write_isolated_home
from hermes_eval.redact import redact_obj

KNOWN = {
    "hermes-cli",
    "hermes-telegram",
    "hermes-discord",
    "terminal",
    "web",
    "file",
}

TEXT_TOOL_RE = re.compile(
    r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:',
    re.DOTALL,
)

PSEUDO_CALL = (
    '{"name": "write_file", "arguments": {"path": "proof.txt", '
    '"content": "NONCE"}}'
)


def _load_module(hermes_root: Path, rel: str, name: str):
    path = hermes_root / rel
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _warnings(hermes_root: Path, platform_toolsets: dict) -> list[str]:
    mod = _load_module(
        hermes_root,
        "hermes_cli/toolset_validation.py",
        f"eval_toolset_validation_{id(hermes_root)}",
    )
    if mod is None or not hasattr(mod, "validate_platform_toolsets"):
        return []
    return list(mod.validate_platform_toolsets(platform_toolsets, lambda n: n in KNOWN))


def _empty_list_warning(warnings: list[str], platform: str = "cli") -> bool:
    plat = platform.lower()
    for item in warnings:
        low = str(item).lower()
        if plat in low and ("empty toolset" in low or "empty list" in low):
            return True
        if "zero valid toolsets" in low and plat in low:
            return True
    return False


def _resolve_tool_names(hermes_root: Path, platform_toolsets: dict, platform: str) -> list[str]:
    raw = platform_toolsets.get(platform)
    if isinstance(raw, list) and len(raw) == 0:
        return []
    names = raw if isinstance(raw, list) else [raw] if raw else ["hermes-cli"]
    toolsets_mod = _load_module(
        hermes_root, "toolsets.py", f"eval_toolsets_{id(hermes_root)}"
    )
    if toolsets_mod is None or not hasattr(toolsets_mod, "resolve_toolset"):
        return [str(n) for n in names]
    resolved: list[str] = []
    seen: set[str] = set()
    for name in names:
        for tool in toolsets_mod.resolve_toolset(str(name)) or []:
            if tool not in seen:
                seen.add(tool)
                resolved.append(tool)
    return resolved


def _dispatch_write_file(hermes_root: Path, proof: Path, nonce: str) -> tuple[bool, str]:
    file_mod = _load_module(
        hermes_root, "tools/file_tools.py", f"eval_file_tools_{id(hermes_root)}"
    )
    if file_mod is None or not hasattr(file_mod, "write_file_tool"):
        proof.write_text(nonce, encoding="utf-8")
        return True, "fallback-direct-write"
    result = file_mod.write_file_tool(str(proof), nonce)
    ok = proof.is_file() and proof.read_text(encoding="utf-8") == nonce
    return ok, str(result)[:240]


def _run_arm(
    *,
    hermes_root: Path,
    arm: str,
    platform_toolsets: dict,
    workspace: Path,
) -> dict:
    nonce = f"EVAL-{uuid.uuid4().hex[:12]}"
    # One canonical target is shared by dispatch, the external oracle, and
    # result metadata. Never reconstruct it from cwd or tool output.
    proof = (workspace / "proof.txt").resolve()
    warnings = _warnings(hermes_root, platform_toolsets)
    schemas = _resolve_tool_names(hermes_root, platform_toolsets, "cli")
    write_available = "write_file" in schemas
    events: list[dict] = []
    transcript = ""
    finish_reason = "stop"
    tool_calls = 0
    tool_ok = 0
    tool_fail = 0
    invalid = 0

    if schemas:
        # Fake model: structured tool call because Hermes exposed tools.
        events.append(
            {
                "type": "llm",
                "finish_reason": "tool_calls",
                "tool_schemas": len(schemas),
            }
        )
        if write_available:
            ok, detail = _dispatch_write_file(hermes_root, proof, nonce)
            tool_calls = 1
            tool_ok = 1 if ok else 0
            tool_fail = 0 if ok else 1
            events.append(
                {
                    "type": "tool",
                    "name": "write_file",
                    "status": "ok" if ok else "error",
                    "detail": detail,
                }
            )
            transcript = "wrote proof.txt" if ok else f"write_file failed: {detail}"
            finish_reason = "stop"
        else:
            invalid = 1
            transcript = PSEUDO_CALL.replace("NONCE", nonce)
            finish_reason = "stop"
    else:
        # Fake model: same intent, but dumped as text because no schemas.
        transcript = (
            "I'll write the marker file now.\n\n"
            + PSEUDO_CALL.replace("NONCE", nonce)
        )
        finish_reason = "stop"
        events.append(
            {
                "type": "llm",
                "finish_reason": "stop",
                "tool_schemas": 0,
                "textual_pseudo_tool_call": True,
            }
        )

    text_as_tool = bool(TEXT_TOOL_RE.search(transcript)) and tool_calls == 0
    proof_exists = proof.is_file() and proof.read_text(encoding="utf-8") == nonce
    warning_emitted = _empty_list_warning(warnings)
    return {
        "arm": arm,
        "nonce": nonce,
        "warnings": [str(w) for w in warnings],
        "warning_emitted": warning_emitted,
        "tool_schemas": schemas,
        "tool_schema_count": len(schemas),
        "write_file_exposed": write_available,
        "transcript": transcript,
        "finish_reason": finish_reason,
        "events": events,
        "tool_calls": tool_calls,
        "tool_calls_success": tool_ok,
        "tool_calls_failed": tool_fail,
        "invalid_tool_calls": invalid,
        "textual_pseudo_tool_call": text_as_tool,
        "proof_exists": proof_exists,
        "proof_path": str(proof),
    }


def run(hermes_root: Path, hermes_sha: str, out_dir: Path) -> dict:
    started = time.perf_counter()
    workspace = write_isolated_home()
    control_cfg = {"cli": ["hermes-cli"]}
    fault_cfg = {
        "cli": [],
        "telegram": ["hermes-telegram"],
        "discord": ["hermes-discord"],
    }
    (workspace / "control").mkdir(exist_ok=True)
    (workspace / "fault").mkdir(exist_ok=True)
    # This runner imports Hermes in-process. Apply (rather than merely build)
    # the isolated environment so product config cannot select a namespace
    # invisible to the host-side proof oracle.
    with applied_isolated_env(workspace):
        control = _run_arm(
            hermes_root=hermes_root,
            arm="control",
            platform_toolsets=control_cfg,
            workspace=workspace / "control",
        )
        fault = _run_arm(
            hermes_root=hermes_root,
            arm="fault",
            platform_toolsets=fault_cfg,
            workspace=workspace / "fault",
        )

    control_ok = bool(control["proof_exists"] and control["tool_schema_count"] > 0)
    # Fault arm: tools stay 0 (fail-closed). Loud diagnostic is the version
    # discriminator. Proof must not exist — that would mean we invented a tool.
    fault_closed = (
        fault["tool_schema_count"] == 0
        and fault["tool_calls"] == 0
        and not fault["proof_exists"]
        and fault["textual_pseudo_tool_call"]
    )
    success = control_ok and fault_closed and fault["warning_emitted"]
    notes = []
    if not control_ok:
        notes.append("control arm failed: expected write_file proof under a normal toolset")
    if not fault_closed:
        notes.append("fault arm did not stay fail-closed / text-as-tool")
    if fault_closed and not fault["warning_emitted"]:
        notes.append("fault arm silent: zero tools, no named empty-list diagnostic")
    if fault["warning_emitted"]:
        notes.append("fault arm surfaced a named empty-list / zero-toolset diagnostic")

    duration_ms = (time.perf_counter() - started) * 1000
    result = {
        "fixture": "zero-toolset",
        "fixture_version": 2,
        "hermes_ref": hermes_sha,
        "model": "hermes-eval-fake",
        "provider": "synthetic",
        "success": success,
        "turns": 1,
        "tool_calls": control["tool_calls"] + fault["tool_calls"],
        "tool_calls_success": control["tool_calls_success"] + fault["tool_calls_success"],
        "tool_calls_failed": control["tool_calls_failed"] + fault["tool_calls_failed"],
        "invalid_tool_calls": control["invalid_tool_calls"] + fault["invalid_tool_calls"],
        "wasted_tool_calls": 1 if fault["textual_pseudo_tool_call"] else 0,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "recovered": fault["warning_emitted"] if fault_closed else False,
        "recovery_turns": 0 if fault["warning_emitted"] else None,
        "recovery_tool_calls": 0,
        "cache_prefix_stable": None,
        "duration_ms": round(duration_ms, 1),
        "notes": notes,
        "not_observable": ["input_tokens", "output_tokens", "total_tokens", "cache_prefix_stable"],
        "extras": {
            "control": control,
            "fault": fault,
            "control_success": control_ok,
            "fault_fail_closed": fault_closed,
            "diagnostic_emitted": fault["warning_emitted"],
            "hermes_home": str(workspace),
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
