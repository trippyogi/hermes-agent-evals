"""Deterministic, corpus-scoped sanitization with fail-closed reporting."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|session[_-]?ticket|access[_-]?token|refresh[_-]?token|credential|token)", re.I)
_INLINE_SECRET = re.compile(
    r"(?i)\b((?:[A-Z][A-Z0-9_]{1,63}_)?(?:API[_-]?KEY|TOKEN|PASSWORD|SECRET|SESSION[_-]?TICKET|COOKIE|AUTHORIZATION))\s*([=:])\s*([^\s,;\"']{4,})"
)
_COOKIE_HEADER = re.compile(r"(?i)\b(Cookie\s*:)\s*([^\s,;\"']{4,})")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_KEY = re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{8,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
_POSIX_HOME = re.compile(r"(?<![\w])/(?:home|Users)/[^/\s\"']+(?:/[^\s\"']*)?")
_POSIX_ABSOLUTE = re.compile(r"(?<![:/\w])/(?:[A-Za-z0-9._~+-]+/)*[A-Za-z0-9._~+-]+")
_WINDOWS_HOME = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s\"']+(?:\\[^\s\"']*)?")
_WINDOWS_ABSOLUTE = re.compile(r"(?i)\b[A-Z]:\\(?:[^\\\s\"']+\\)*[^\\\s\"']+")
_UNC = re.compile(r"\\\\[^\\\s]+\\[^\s\"']+")
_RESIDUAL = (_BEARER, _KEY, _JWT, _INLINE_SECRET, _COOKIE_HEADER, _POSIX_HOME, _POSIX_ABSOLUTE, _WINDOWS_HOME, _WINDOWS_ABSOLUTE, _UNC)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


@dataclass
class CorpusSanitizer:
    corpus_id: str
    replacements: dict[str, dict[str, str]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    fingerprinted: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)

    def _stable(self, kind: str, original: str) -> str:
        if original.startswith(f"<{kind}_") or original.startswith("<CREDENTIAL_FINGERPRINT_"):
            return original
        mapping = self.replacements.setdefault(kind, {})
        if original not in mapping:
            # Stable across chunking/order while remaining unlinkable across corpora.
            mapping[original] = f"<{kind}_FINGERPRINT_{_fingerprint(f'{self.corpus_id}:{kind}:{original}')}>"
        return mapping[original]

    def _text(self, value: str, pointer: str) -> str:
        out = _BEARER.sub(lambda m: f"<CREDENTIAL_FINGERPRINT_{_fingerprint(self.corpus_id + ':' + m.group(0))}>", value)
        out = _KEY.sub(lambda m: f"<CREDENTIAL_FINGERPRINT_{_fingerprint(self.corpus_id + ':' + m.group(0))}>", out)
        out = _JWT.sub(lambda m: f"<CREDENTIAL_FINGERPRINT_{_fingerprint(self.corpus_id + ':' + m.group(0))}>", out)
        out = _COOKIE_HEADER.sub(
            lambda m: f"{m.group(1)} <CREDENTIAL_FINGERPRINT_{_fingerprint(self.corpus_id + ':' + m.group(2))}>", out
        )
        out = _INLINE_SECRET.sub(
            lambda m: f"{m.group(1)}{m.group(2)}<CREDENTIAL_FINGERPRINT_{_fingerprint(self.corpus_id + ':' + m.group(3))}>", out
        )
        out = _POSIX_HOME.sub(lambda m: self._stable("PATH", m.group(0)), out)
        out = _WINDOWS_HOME.sub(lambda m: self._stable("PATH", m.group(0)), out)
        out = _UNC.sub(lambda m: self._stable("PATH", m.group(0)), out)
        out = _WINDOWS_ABSOLUTE.sub(lambda m: self._stable("PATH", m.group(0)), out)
        out = _POSIX_ABSOLUTE.sub(lambda m: self._stable("PATH", m.group(0)), out)
        out = _EMAIL.sub(lambda m: self._stable("EMAIL", m.group(0)), out)
        if out != value:
            self.replaced.append(pointer)
        return out

    def sanitize(self, value: Any, pointer: str = "$") -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key in sorted(value, key=str):
                child = f"{pointer}/{key}"
                item = value[key]
                if _SECRET_KEY.search(str(key)):
                    if item is None or item == "":
                        result[key] = None
                    elif isinstance(item, str) and item.startswith("<CREDENTIAL_FINGERPRINT_"):
                        result[key] = item
                    else:
                        result[key] = f"<CREDENTIAL_FINGERPRINT_{_fingerprint(self.corpus_id + ':' + str(item))}>"
                        self.fingerprinted.append(child)
                elif str(key).lower() in {"environment", "env", "memory", "memories"}:
                    result[key] = "<REMOVED>"
                    self.removed.append(child)
                else:
                    result[key] = self.sanitize(item, child)
            return result
        if isinstance(value, list):
            return [self.sanitize(item, f"{pointer}/{index}") for index, item in enumerate(value)]
        if isinstance(value, str):
            return self._text(value, pointer)
        return value

    def report(self, sanitized: Any, *, source_type_known: bool, manual_spot_check: bool) -> dict[str, Any]:
        findings = scan_sanitized(sanitized)
        safe = source_type_known and manual_spot_check and not findings
        return {
            "redaction_version": 1,
            "corpus_id": self.corpus_id,
            "fields_removed": len(set(self.removed)),
            "fields_fingerprinted": len(set(self.fingerprinted)),
            "fields_replaced": len(set(self.replaced)),
            "removed_pointers": sorted(set(self.removed)),
            "fingerprinted_pointers": sorted(set(self.fingerprinted)),
            "replaced_pointers": sorted(set(self.replaced)),
            "scans_run": ["credential", "absolute_path", "email"],
            "findings": findings,
            "warnings": [] if source_type_known else ["unknown source type"],
            "source_type_known": source_type_known,
            "manual_review_required": not manual_spot_check,
            "safe_to_commit": safe,
        }


def scan_sanitized(value: Any) -> list[dict[str, str]]:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    scan_text = re.sub(r"<CREDENTIAL_FINGERPRINT_[0-9a-f]{8}>", "", text)
    findings: list[dict[str, str]] = []
    for pattern in _RESIDUAL:
        if pattern.search(scan_text):
            findings.append({"class": "sensitive_pattern", "pattern": pattern.pattern})
    # Stable email placeholders are allowed; residual addresses are not.
    scrubbed = re.sub(r"<EMAIL_(?:\d{3}|FINGERPRINT_[0-9a-f]{8})>", "", text)
    if _EMAIL.search(scrubbed):
        findings.append({"class": "email", "pattern": _EMAIL.pattern})
    return findings
