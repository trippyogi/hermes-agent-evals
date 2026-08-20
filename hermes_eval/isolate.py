"""Isolated temp HERMES_HOME. Never touch the user's real Hermes home."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MINIMAL_CONFIG = """\
model:
  provider: custom
  default: hermes-eval-synthetic
  base_url: http://127.0.0.1:9
  api_key: eval-not-a-secret
fallback_providers: []
memory:
  enabled: false
session_reset:
  mode: disabled
timezone: UTC
"""


EVAL_CREDENTIAL_ENV = (
    "HERMES_EVAL_API_KEY",
    "HERMES_EVAL_PROVIDER",
    "HERMES_EVAL_MODEL",
    "HERMES_EVAL_BASE_URL",
    "HERMES_EVAL_REPS",
    "HERMES_EVAL_MAX_TURNS",
    "HERMES_EVAL_TEMPERATURE",
    "HERMES_EVAL_REASONING",
)


def eval_credentials() -> dict[str, str | None]:
    """Read only HERMES_EVAL_* process env. Never ~/.hermes."""
    return {name: os.environ.get(name) for name in EVAL_CREDENTIAL_ENV}


def live_eval_ready() -> tuple[bool, str]:
    creds = eval_credentials()
    missing = [
        name
        for name in ("HERMES_EVAL_API_KEY", "HERMES_EVAL_PROVIDER", "HERMES_EVAL_MODEL")
        if not (creds.get(name) or "").strip()
    ]
    if missing:
        return False, "missing " + ", ".join(missing) + " (do not read ~/.hermes)"
    return True, "HERMES_EVAL_* present"


def write_isolated_home(
    root: Path | None = None,
    config_yaml: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    home = Path(tempfile.mkdtemp(prefix="hermes-eval-home-", dir=root))
    (home / "config.yaml").write_text(config_yaml or MINIMAL_CONFIG, encoding="utf-8")
    (home / ".env").write_text(
        "# isolated eval home — no user credentials\n", encoding="utf-8"
    )
    if extra_files:
        for rel, body in extra_files.items():
            path = home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    return home


@contextmanager
def isolated_env(home: Path, extra: dict[str, str] | None = None) -> Iterator[dict[str, str]]:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    env["HERMES_YOLO_MODE"] = "1"
    env["HERMES_ACCEPT_HOOKS"] = "1"
    env.pop("HERMES_PROFILE", None)
    env.pop("HERMES_CONFIG", None)
    # Do not inherit user provider keys into the SUT process.
    # HERMES_EVAL_* may be remapped by the live runner into a single
    # provider env for the child; everything else is stripped.
    for key in list(env):
        upper = key.upper()
        if upper.endswith("_API_KEY") or upper.endswith("_TOKEN"):
            if upper.startswith("HERMES_EVAL_"):
                continue
            env.pop(key, None)
    if extra:
        extra = {k: v for k, v in extra.items() if k != "keep_eval_provider_env"}
        env.update(extra)
    yield env
