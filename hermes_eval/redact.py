"""Never persist raw API credentials in eval artifacts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

_SECRET_KEY_RE = re.compile(
    r"^(api[_-]?key|token|authorization|password|secret|access_token|credential_fp)$",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_SK_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,})\b")


def credential_class(value: Any) -> str | None:
    """Classify a credential without storing it."""
    if value is None:
        return None
    text = str(value)
    if not text:
        return "empty"
    if text == "aws-sdk":
        return "bedrock-sentinel"
    if text == "moa-virtual-provider":
        return "moa-sentinel"
    if text.startswith("sk-ant-"):
        return "anthropic-key"
    if text.startswith("sk-"):
        return "openai-key"
    if "codex" in text.lower() or text.startswith("codex-"):
        return "codex-key"
    if text.startswith("portal-") or "jwt" in text.lower():
        return "portal-jwt"
    return "opaque"


def credential_fingerprint(value: Any) -> str | None:
    """Stable non-reversible handle for identity comparison."""
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{credential_class(text)}:{digest}"


def redact_text(text: str) -> str:
    out = _BEARER_RE.sub("Bearer <redacted>", text)
    out = _SK_RE.sub("<redacted-key>", out)
    return out


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned = {}
        for key, value in obj.items():
            if _SECRET_KEY_RE.search(str(key)):
                cleaned[key] = credential_fingerprint(value)
            else:
                cleaned[key] = redact_obj(value)
        return cleaned
    if isinstance(obj, list):
        return [redact_obj(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj
