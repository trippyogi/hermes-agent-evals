"""Versioned JSON Schema validation for public eval contracts."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from hermes_eval.gitutil import REPO_ROOT


SCHEMAS = {
    "CorpusManifestV1": REPO_ROOT / "evals/schemas/corpus-manifest-v1.schema.json",
    "EpisodeV1": REPO_ROOT / "evals/schemas/episode-v1.schema.json",
    "EvalOpportunityV1": REPO_ROOT / "integrations/gitworthy/eval-opportunity-v1.schema.json",
    "EvalEvidenceV1": REPO_ROOT / "integrations/gitworthy/eval-evidence-v1.schema.json",
}


def load_schema(name: str) -> dict[str, Any]:
    try:
        path = SCHEMAS[name]
    except KeyError as exc:
        raise ValueError(f"unknown schema: {name}") from exc
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validation_errors(payload: dict[str, Any], name: str | None = None) -> list[str]:
    schema_name = name or str(payload.get("schema") or "")
    validator = Draft202012Validator(load_schema(schema_name), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    rendered = [f"{'/'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in errors]
    # jsonschema's RFC3339 checker is an optional dependency. Keep public
    # contracts fail-closed even in the dependency-minimal harness install.
    timestamp = payload.get("evaluated_at") or payload.get("retrieved_at")
    if isinstance(timestamp, str):
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            rendered.append("timestamp: is not a valid ISO-8601 date-time")
    return rendered


def validate_contract(payload: dict[str, Any], name: str | None = None) -> None:
    errors = validation_errors(payload, name)
    if errors:
        raise ValueError("; ".join(errors))
