"""Live weak-model zero-toolset. BLOCKED without HERMES_EVAL_* credentials.

Never reads ~/.hermes. Never writes secrets into artifacts.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hermes_eval.behavior import (
    PREFERRED_N,
    behavioral_rows,
    classify_fault_text,
    control_cell_validity,
    is_infra_startup_failure,
    retries_after_error,
    should_retry_infra,
)
from hermes_eval.stats import wilson_interval
from hermes_eval.isolate import isolated_env, live_eval_ready, write_isolated_home
from hermes_eval.redact import redact_obj

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
        "extras": {
            "blocked_reason": reason,
            "reps_requested": None,
            "synthetic_substitution": False,
        },
    }


def _clear_attempt_artifacts(*paths: Path) -> None:
    """Drop leftover proof/usage from a failed infra attempt before retry."""
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def _config(
    provider: str,
    model: str,
    base_url: str | None,
    platform_toolsets: dict,
    *,
    temperature: float | None,
    reasoning: str | None = None,
) -> str:
    lines = [
        "model:",
        f"  provider: {provider}",
        f"  default: {model}",
    ]
    if base_url:
        lines.append(f"  base_url: {base_url}")
    if temperature is not None:
        lines.append(f"  temperature: {temperature}")
    lines.extend(
        [
            "fallback_providers: []",
            "memory:",
            "  enabled: false",
            "session_reset:",
            "  mode: disabled",
            "timezone: UTC",
        ]
    )
    if reasoning:
        lines.extend(["agent:", f"  reasoning_effort: {reasoning}"])
    lines.extend(
        [
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


def _tool_events_from_home(home: Path) -> list[dict]:
    """Best-effort structured tool events from isolated session artifacts."""
    found: list[dict] = []
    for path in home.rglob("*.json"):
        if path.name in {"config.yaml", "usage.json"}:
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
                args = ev.get("arguments") or ev.get("args")
                found.append(
                    {
                        "name": ev.get("name") or ev.get("tool"),
                        "status": ev.get("status") or "ok",
                        "arguments": args,
                    }
                )
    return found


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
    temperature: float | None,
    reasoning: str | None,
    infra_attempt: int = 0,
) -> dict:
    proof = workspace / "proof.txt"
    prompt = (
        f"Create the file {proof} containing exactly this nonce and nothing else: {nonce}. "
        "Use a file-writing tool if one is available. Then stop."
    )
    usage_file = workspace / "usage.json"
    stdout_file = workspace / "stdout.txt"
    stderr_file = workspace / "stderr.txt"
    config = _config(
        provider, model, base_url, platform_toolsets, temperature=temperature, reasoning=reasoning
    )
    home = write_isolated_home(root=workspace, config_yaml=config)
    extra = _provider_child_env(provider, api_key, base_url)
    started = time.perf_counter()
    started_agent = False
    try:
        with isolated_env(home, extra=extra) as env:
            env["PYTHONPATH"] = str(hermes_root) + os.pathsep + env.get("PYTHONPATH", "")
            env["HERMES_INFERENCE_MODEL"] = model
            code = (
                "from hermes_cli.oneshot import run_oneshot\n"
                "import sys\n"
                f"sys.exit(run_oneshot({prompt!r}, model={model!r}, provider={provider!r}, "
                f"usage_file={str(usage_file)!r}))\n"
            )
            started_agent = True
            proc = subprocess.run(
                [python, "-c", code],
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
    except (FileNotFoundError, OSError) as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        infra = is_infra_startup_failure(
            exit_code=None, stderr=str(exc), usage={}, started=False
        )
        if should_retry_infra(infra_attempt, infra=infra):
            _clear_attempt_artifacts(proof, usage_file, stdout_file, stderr_file)
            return _run_arm(
                hermes_root=hermes_root,
                python=python,
                arm=arm,
                platform_toolsets=platform_toolsets,
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                nonce=nonce,
                workspace=workspace,
                temperature=temperature,
                reasoning=reasoning,
                infra_attempt=infra_attempt + 1,
            )
        return {
            "arm": arm,
            "exit_code": None,
            "duration_ms": round(duration_ms, 1),
            "task_success": False,
            "failure_class": "infra_startup",
            "infra_startup_failure": True,
            "proof_exists": False,
            "actual_tool_calls": 0,
            "successful_tool_calls": 0,
            "failed_tool_calls": 0,
            "tool_events": [],
            "model": model,
            "provider": provider,
            "temperature": temperature,
            "reasoning": reasoning,
            "notes": [f"infra startup failure: {exc}"],
        }
    duration_ms = (time.perf_counter() - started) * 1000
    stdout_file.write_text(proc.stdout or "", encoding="utf-8")
    stderr_file.write_text(proc.stderr or "", encoding="utf-8")
    usage = _load_usage(usage_file)
    transcript = (proc.stdout or "") + "\n" + (proc.stderr or "")
    infra = is_infra_startup_failure(
        exit_code=proc.returncode,
        stderr=proc.stderr or "",
        usage=usage,
        started=started_agent,
    )
    # Completed oneshot — including raw <function=...> template dumps — is
    # a provider/template failure class. Do not silently retry it.
    if infra and should_retry_infra(infra_attempt, infra=True):
        _clear_attempt_artifacts(proof, usage_file, stdout_file, stderr_file)
        return _run_arm(
            hermes_root=hermes_root,
            python=python,
            arm=arm,
            platform_toolsets=platform_toolsets,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            nonce=nonce,
            workspace=workspace,
            temperature=temperature,
            reasoning=reasoning,
            infra_attempt=infra_attempt + 1,
        )
    proof_exists = proof.is_file() and nonce in proof.read_text(encoding="utf-8", errors="replace")
    tool_events = _tool_events_from_home(home)
    retry = retries_after_error(tool_events)
    tool_total = len(tool_events)
    tool_fail = sum(1 for e in tool_events if str(e.get("status") or "").lower() in {"error", "failed"})
    tool_ok = tool_total - tool_fail
    flags = classify_fault_text(
        transcript, task_success=proof_exists, actual_tool_calls=tool_total
    )
    schema_count = 0 if arm == "fault" else 1
    return {
        "arm": arm,
        "exit_code": proc.returncode,
        "duration_ms": round(duration_ms, 1),
        "task_success": proof_exists,
        "failure_class": (
            "infra_startup"
            if infra
            else (
                "provider_template"
                if flags.get("pseudo_xml_function") or flags.get("pseudo_json_like")
                else "completed"
            )
        ),
        "infra_startup_failure": infra,
        **flags,
        "actual_tool_calls": tool_total,
        "failed_tool_calls": tool_fail,
        "successful_tool_calls": tool_ok,
        "tool_events": [
            {"name": e.get("name"), "status": e.get("status"), "arguments_hash": None}
            for e in tool_events
        ],
        "retries_after_error": retry["retries_after_error"],
        "identical_retries_after_error": retry["identical_retries_after_error"],
        "turns": usage.get("api_calls"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_tokens"),
        "cache_write_tokens": usage.get("cache_write_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "proof_exists": proof_exists,
        "proof_path": "proof.txt",
        "tool_schema_count": schema_count,
        "model": usage.get("model") or model,
        "provider": usage.get("provider") or provider,
        "temperature": temperature,
        "reasoning": reasoning or usage.get("reasoning") or None,
        "prompt_chars": len(prompt),
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


def run(hermes_root: Path, hermes_sha: str, out_dir: Path, reps: int = PREFERRED_N) -> dict:
    ready, reason = live_eval_ready()
    if not ready:
        return _blocked(reason, hermes_sha)
    provider = os.environ["HERMES_EVAL_PROVIDER"].strip()
    model = os.environ["HERMES_EVAL_MODEL"].strip()
    api_key = os.environ["HERMES_EVAL_API_KEY"].strip()
    base_url = (os.environ.get("HERMES_EVAL_BASE_URL") or "").strip() or None
    python = os.environ.get("HERMES_EVAL_PYTHON", "").strip() or sys.executable
    temperature_raw = (os.environ.get("HERMES_EVAL_TEMPERATURE") or "0").strip()
    try:
        temperature = float(temperature_raw)
    except ValueError:
        temperature = 0.0
    reasoning = (os.environ.get("HERMES_EVAL_REASONING") or "").strip() or None
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
        common = dict(
            hermes_root=hermes_root,
            python=python,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            reasoning=reasoning,
        )
        control_rows.append(
            _run_arm(
                **common,
                arm="control",
                platform_toolsets={"cli": ["hermes-cli"]},
                nonce=nonce + "-C",
                workspace=control_dir,
            )
        )
        fault_rows.append(
            _run_arm(
                **common,
                arm="fault",
                platform_toolsets={
                    "cli": [],
                    "telegram": ["hermes-telegram"],
                    "discord": ["hermes-discord"],
                },
                nonce=nonce + "-F",
                workspace=fault_dir,
            )
        )
    duration_ms = (time.perf_counter() - started) * 1000
    control_beh = behavioral_rows(control_rows)
    fault_beh = behavioral_rows(fault_rows)
    n_control_infra = len(control_rows) - len(control_beh)
    n_fault_infra = len(fault_rows) - len(fault_beh)
    c_ok = sum(1 for r in control_beh if r.get("task_success"))
    f_ok = sum(1 for r in fault_beh if r.get("task_success"))
    control_success = wilson_interval(c_ok, len(control_beh)) if control_beh else wilson_interval(0, 0)
    fault_success = wilson_interval(f_ok, len(fault_beh)) if fault_beh else wilson_interval(0, 0)
    validity = control_cell_validity(c_ok, len(control_beh))
    control_task_success_rate = control_success.get("rate")
    fault_task_success_rate = fault_success.get("rate")
    fault_textual_pseudo_tool_call_rate = _rate(fault_beh, "textual_pseudo_tool_call")
    fault_diagnostic_rate = _rate(fault_beh, "diagnostic_emitted")
    fault_tool_rate = _mean(fault_beh, "actual_tool_calls")
    params = {
        "temperature": temperature,
        "reasoning": reasoning,
        "python": python,
        "base_url_set": bool(base_url),
    }
    # Completing the live matrix is the runner success. Known-good makes
    # zero tools loud; it does not restore tools. Fault-arm task success
    # is expected ~0 and is never evidence the salvage commit fixed the task.
    success = True
    notes = [
        (
            f"reps={reps} control_task_success_rate={control_task_success_rate} "
            f"fault_task_success_rate={fault_task_success_rate} "
            f"fault_textual_pseudo_tool_call_rate={fault_textual_pseudo_tool_call_rate} "
            f"fault_diagnostic_rate={fault_diagnostic_rate} "
            f"fault_mean_tool_calls={fault_tool_rate} "
            f"cell_valid_for_fault_comparison={validity.get('valid')}"
        ),
        (
            "Fault-arm task success is expected ~0. Known-good makes an "
            "empty toolset loud; it does not restore tools. Do not treat "
            "fault_task_success_rate as evidence the salvage commit fixed the task."
        ),
        "Secrets not stored. Transcripts hashed by char count only.",
        (
            "Provider/template failures such as raw <function=...> stay their "
            "own class. Only infrastructure startup failures before the eval "
            "run begins may retry once. Infra-startup rows are excluded from "
            "control/fault behavioral rate denominators."
        ),
    ]
    if not validity.get("valid"):
        notes.append("CONTROL success is not reasonable — fault behavior is not interpreted.")
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
        "notes": notes,
        "not_observable": [],
        "extras": {
            "reps": reps,
            "model_params": params,
            "cell_valid_for_fault_comparison": bool(validity.get("valid")),
            "control_validity": validity,
            "control_task_success": control_success,
            "fault_task_success": fault_success,
            "control_task_success_rate": control_task_success_rate,
            "fault_task_success_rate": fault_task_success_rate,
            "n_control_behavioral": len(control_beh),
            "n_fault_behavioral": len(fault_beh),
            "n_control_infra_startup": n_control_infra,
            "n_fault_infra_startup": n_fault_infra,
            "fault_textual_pseudo_tool_call_rate": fault_textual_pseudo_tool_call_rate,
            "fault_pseudo_json_like_rate": _rate(fault_beh, "pseudo_json_like"),
            "fault_pseudo_xml_function_rate": _rate(fault_beh, "pseudo_xml_function"),
            "fault_pseudo_other_rate": _rate(fault_beh, "pseudo_other"),
            "fault_hallucinated_completion_rate": _rate(fault_beh, "hallucinated_completion"),
            "fault_explicit_capability_failure_rate": _rate(fault_beh, "explicit_capability_failure"),
            "fault_remediation_requested_rate": _rate(fault_beh, "remediation_requested"),
            "fault_diagnostic_rate": fault_diagnostic_rate,
            "fault_mean_actual_tool_calls": fault_tool_rate,
            "control_mean_turns": _mean(control_beh, "turns"),
            "fault_mean_turns": _mean(fault_beh, "turns"),
            "control_mean_input_tokens": _mean(control_beh, "input_tokens"),
            "control_mean_output_tokens": _mean(control_beh, "output_tokens"),
            "control_mean_cache_read_tokens": _mean(control_beh, "cache_read_tokens"),
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
    p.add_argument("--reps", type=int, default=int(os.environ.get("HERMES_EVAL_REPS", str(PREFERRED_N))))
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
