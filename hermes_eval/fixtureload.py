"""Load fixture YAML without requiring PyYAML."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hermes_eval.gitutil import REPO_ROOT, expand_ref

FIXTURE_SCHEMA_VERSION = 2
CLASSIFICATIONS = (
    "production_replay",
    "fault_injected_invariant",
    "state_transition",
    "agent_behavior",
    "instrumentation",
)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    if value in {"true", "True"}:
        return True  # type: ignore[return-value]
    if value in {"false", "False"}:
        return False  # type: ignore[return-value]
    if value in {"null", "None", "~"}:
        return None  # type: ignore[return-value]
    if value.isdigit():
        return int(value)  # type: ignore[return-value]
    return value


def load_fixture_yaml(path: Path) -> dict[str, Any]:
    """Parse fixture YAML. Prefer PyYAML; fall back to a tiny subset parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        for key in ("known_bad", "known_good"):
            if data.get(key):
                data[key] = expand_ref(str(data[key]))
        data.setdefault("schema_version", FIXTURE_SCHEMA_VERSION)
        return data
    except ImportError:
        pass
    return _load_fixture_yaml_subset(path)


def _load_fixture_yaml_subset(path: Path) -> dict[str, Any]:
    """Parse the simple fixture YAML used in this repo.

    Supports scalars, string lists, and one-level nested maps. Not a
    general YAML parser.
    """
    data: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any] | list[Any]]] = [(-1, data)]
    pending_list_key: str | None = None
    pending_list_indent = 0

    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if line.startswith("- "):
            item = _unquote(line[2:])
            if isinstance(current, list):
                current.append(item)
            elif pending_list_key is not None and indent >= pending_list_indent:
                bucket = current.setdefault(pending_list_key, [])
                if not isinstance(bucket, list):
                    bucket = []
                    current[pending_list_key] = bucket
                bucket.append(item)
            continue

        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            nested: dict[str, Any] = {}
            current[key] = nested
            stack.append((indent, nested))
            pending_list_key = key
            pending_list_indent = indent + 2
            continue
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            current[key] = [_unquote(p.strip()) for p in inner.split(",") if p.strip()] if inner else []
            continue
        current[key] = _unquote(rest)
        pending_list_key = None

    if "known_bad" in data:
        data["known_bad"] = expand_ref(str(data["known_bad"]))
    if "known_good" in data:
        data["known_good"] = expand_ref(str(data["known_good"]))
    data.setdefault("schema_version", FIXTURE_SCHEMA_VERSION)
    return data


def fixture_path(fixture_id: str) -> Path:
    return REPO_ROOT / "evals" / "fixtures" / f"{fixture_id}.yaml"


def load_fixture(fixture_id: str) -> dict[str, Any]:
    path = fixture_path(fixture_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    return load_fixture_yaml(path)


def load_manifest() -> dict[str, Any]:
    path = REPO_ROOT / "evals" / "provenance" / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_expected_historical() -> dict[str, Any]:
    path = REPO_ROOT / "evals" / "provenance" / "expected-historical.json"
    return json.loads(path.read_text(encoding="utf-8"))
