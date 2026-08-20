"""Live weak-model zero-toolset. BLOCKED without HERMES_EVAL_* credentials.

Never reads ~/.hermes. Never writes secrets into artifacts.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hermes_eval.isolate import isolated_env, live_eval_ready, write_isolated_home
from hermes_eval.redact import redact_obj

TEXT_TOOL_RE = re.compile(
    r'(\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:)|'
    r"(<function=\w+>)|"
    r"(```(?:json)?\s*\{\s*\"name\")",
    re.DOTALL,
)

PROVIDER_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai-codex": "OPENAI_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


def _blocked(reason: str, hermes_sha: str | None) -> dict:
    return {
        "fixture": "zero-toolset-live",
        "fixture_version": 1,
        "hermes_ref": hermes_sha,
        "model": None,
        "provider": None,
        "success": False,
        "status": "BLOCKED",
        "turns": None,
        "tool_calls": None,
        "tool_calls_success": None,
        "tool_calls_failed": None,
        "invalid_tool_calls": None,
        "wasted_tool_calls": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "recovered": None,
        "cache_prefix_stable": None,
        "duration_ms": None,
        "notes": [
            "Live matrix BLOCKED. Runner is implemented; no synthetic numbers substituted.",
            reason,
        ],
        "not_observable": [
            "task_success",
            "textual_pseudo_tool_call",
            "actual_tool_calls",
            "turns",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "duration",
        ],
        "extras": {"blocked_reason": reason, "reps_requested": None},
    }


def _config(provider: str, model: str, base_url: str | None, platform_toolsets: dict) -> str:
    lines = [
        "model:",
        f"  provider: {provider}",
        f"  default: {model}",
    ]
    if base_url:
        lines.append(f"  base_url: {base_url}")
    lines.extend(
        [
            "fallback_providers: []",
            "memory:",
            "  enabled: false",
            "session_reset:",
            "  mode: disabled",
            "timezone: UTC",
            "platform_toolsets:",
        ]
    )
    for plat, tools in platform_toolsets.items():
        if tools:
            joined = ", ".join(tools)
            lines.append(f"  {plat}: [{joined}]")
        else:
            lines.append(f"  {plat}: []")
    return "\n".join(lines) + "\n"


def _provider_child_env(provider: str, api_key: str, base_url: str | None) -> dict[str, str]:
    env_name = PROVIDER_ENV.get(provider, "CUSTOM_API_KEY")
    extra = {env_name: api_key}
    if base_url:
        extra["HERMES_EVAL_BASE_URL"] = base_url
    return extra


def _load_usage(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _count_tools_from_home(home: Path) -> tuple[int, int, int]:
    """Best-effort structured tool counts from isolated session artifacts."""
    total = success = failed = 0
    for path in home.rglob("*.json"):
        if path.name in {"config.yaml"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        events = payload.get("events") if isinstance(payload, dict) else None
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") in {"tool", "tool_call"} or ev.get("role") == "tool":
                total += 1
                status = str(ev.get("status") or "").lower()
                if status in {"error", "failed"}:
                    failed += 1
                else:
                    success += 1
    return total, success, failed


def _run_arm(
    *,
    hermes_root: Path,
    python: str,
    arm: str,
    platform_toolsets: dict,
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None,
    nonce: str,
    workspace: Path,
) -> dict:
    proof = workspace / "proof.txt"
    prompt = (
        f"Create the file {proof} containing exactly this nonce and nothing else: {nonce}. "
        "Use a file-writing tool if one is available. Then stop."
    )
    usage_file = workspace / "usage.json"
    stdout_file = workspace / "stdout.txt"
    stderr_file = workspace / "stderr.txt"
    config = _config(provider, model, base_url, platform_toolsets)
    home = write_isolated_home(root=workspace, config_yaml=config)
    extra = _provider_child_env(provider, api_key, base_url)
    started = time.perf_counter()
    with isolated_env(home, extra=extra) as env:
        env["PYTHONPATH"] = str(hermes_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["HERMES_INFERENCE_MODEL"] = model
        code = (
            "from hermes_cli.oneshot import run_oneshot\n"
            "import sys\n"
            f"sys.exit(run_oneshot({prompt!r}, model={model!r}, provider={provider!r}, "
            f"usage_file={str(usage_file)!r}))\n"
        )
        proc = subprocess.run(
            [python, "-c", code],
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    duration_ms = (time.perf_counter() - started) * 1000
    stdout_file.write_text(proc.stdout or "", encoding="utf-8")
    stderr_file.write_text(proc.stderr or "", encoding="utf-8")
    usage = _load_usage(usage_file)
    transcript = (proc.stdout or "") + "\n" + (proc.stderr or "")
    proof_exists = proof.is_file() and nonce in proof.read_text(encoding="utf-8", errors="replace")
    tool_total, tool_ok, tool_fail = _count_tools_from_home(home)
    text_as_tool = bool(TEXT_TOOL_RE.search(transcript)) and tool_total == 0
    warning = any(
        token in transcript.lower()
        for token in ("empty toolset", "empty list", "zero valid toolsets", "err_empty_platform")
    )
    return {
        "arm": arm,
        "exit_code": proc.returncode,
        "duration_ms": round(duration_ms, 1),
        "task_success": proof_exists,
        "textual_pseudo_tool_call": text_as_tool,
        "actual_tool_calls": tool_total,
        "failed_tool_calls": tool_fail,
        "successful_tool_calls": tool_ok,
        "turns": usage.get("api_calls"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_tokens"),
        "cache_write_tokens": usage.get("cache_write_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "diagnostic_emitted": warning,
        "proof_exists": proof_exists,
        "model": usage.get("model") or model,
        "provider": usage.get("provider") or provider,
        "transcript_sha_only": True,
        "stdout_chars": len(proc.stdout or ""),
    }


def _rate(rows: list[dict], key: str) -> float | None:
    vals = [1 if r.get(key) else 0 for r in rows]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 3)


def _mean(rows: list[dict], key: str) -> float | None:
    vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
    if not vals:
        return None
    return round(statistics.mean(vals), 3)


def run(hermes_root: Path, hermes_sha: str, out_dir: Path, reps: int = 5) -> dict:
    ready, reason = live_eval_ready()
    if not ready:
        return _blocked(reason, hermes_sha)
    provider = os.environ["HERMES_EVAL_PROVIDER"].strip()
    model = os.environ["HERMES_EVAL_MODEL"].strip()
    api_key = os.environ["HERMES_EVAL_API_KEY"].strip()
    base_url = (os.environ.get("HERMES_EVAL_BASE_URL") or "").strip() or None
    python = os.environ.get("HERMES_EVAL_PYTHON", "").strip() or sys.executable
    started = time.perf_counter()
    root = write_isolated_home()
    control_rows = []
    fault_rows = []
    for i in range(reps):
        nonce = f"LIVE-{uuid.uuid4().hex[:12]}"
        control_dir = root / f"control-{i}"
        fault_dir = root / f"fault-{i}"
        control_dir.mkdir(parents=True)
        fault_dir.mkdir(parents=True)
        control_rows.append(
            _run_arm(
                hermes_root=hermes_root,
                python=python,
                arm="control",
                platform_toolsets={"cli": ["hermes-cli"]},
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                nonce=nonce + "-C",
                workspace=control_dir,
            )
        )
        fault_rows.append(
            _run_arm(
                hermes_root=hermes_root,
                python=python,
                arm="fault",
                platform_toolsets={
                    "cli": [],
                    "telegram": ["hermes-telegram"],
                    "discord": ["hermes-discord"],
                },
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                nonce=nonce + "-F",
                workspace=fault_dir,
            )
        )
    duration_ms = (time.perf_counter() - started) * 1000
    control_task_success_rate = _rate(control_rows, "task_success")
    fault_task_success_rate = _rate(fault_rows, "task_success")
    fault_textual_pseudo_tool_call_rate = _rate(fault_rows, "textual_pseudo_tool_call")
    fault_diagnostic_rate = _rate(fault_rows, "diagnostic_emitted")
    fault_tool_rate = _mean(fault_rows, "actual_tool_calls")
    # Completing the live matrix is the runner success. Known-good makes
    # zero tools loud; it does not restore tools. Fault-arm task success
    # is expected ~0 and is never evidence the salvage commit fixed the task.
    success = True
    result = {
        "fixture": "zero-toolset-live",
        "fixture_version": 2,
        "hermes_ref": hermes_sha,
        "model": model,
        "provider": provider,
        "success": success,
        "status": "RUN",
        "turns": _mean(control_rows, "turns"),
        "tool_calls": _mean(control_rows, "actual_tool_calls"),
        "tool_calls_success": _mean(control_rows, "successful_tool_calls"),
        "tool_calls_failed": _mean(control_rows, "failed_tool_calls"),
        "invalid_tool_calls": None,
        "wasted_tool_calls": None,
        "input_tokens": _mean(control_rows, "input_tokens"),
        "output_tokens": _mean(control_rows, "output_tokens"),
        "total_tokens": _mean(control_rows, "total_tokens"),
        "recovered": None,
        "cache_prefix_stable": None,
        "duration_ms": round(duration_ms, 1),
        "notes": [
            (
                f"reps={reps} control_task_success_rate={control_task_success_rate} "
                f"fault_task_success_rate={fault_task_success_rate} "
                f"fault_textual_pseudo_tool_call_rate={fault_textual_pseudo_tool_call_rate} "
                f"fault_diagnostic_rate={fault_diagnostic_rate} "
                f"fault_mean_tool_calls={fault_tool_rate}"
            ),
            (
                "Fault-arm task success is expected ~0. Known-good makes an "
                "empty toolset loud; it does not restore tools. Do not treat "
                "fault_task_success_rate as evidence the salvage commit fixed the task."
            ),
            "Secrets not stored. Transcripts hashed by char count only.",
        ],
        "not_observable": [],
        "extras": {
            "reps": reps,
            "control_task_success_rate": control_task_success_rate,
            "fault_task_success_rate": fault_task_success_rate,
            "fault_textual_pseudo_tool_call_rate": fault_textual_pseudo_tool_call_rate,
            "fault_diagnostic_rate": fault_diagnostic_rate,
            "fault_mean_actual_tool_calls": fault_tool_rate,
            "control_mean_turns": _mean(control_rows, "turns"),
            "fault_mean_turns": _mean(fault_rows, "turns"),
            "control_mean_input_tokens": _mean(control_rows, "input_tokens"),
            "control_mean_output_tokens": _mean(control_rows, "output_tokens"),
            "control_mean_cache_read_tokens": _mean(control_rows, "cache_read_tokens"),
            "control_runs": control_rows,
            "fault_runs": fault_rows,
        },
    }
    return redact_obj(result)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hermes-root", required=True)
    p.add_argument("--hermes-sha", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--reps", type=int, default=int(os.environ.get("HERMES_EVAL_REPS", "5")))
    args = p.parse_args(argv)
    result = run(Path(args.hermes_root), args.hermes_sha, Path(args.out), reps=args.reps)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": result.get("success"), "status": result.get("status"), "out": args.out}))
    if result.get("status") == "BLOCKED":
        return 1
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
