"""Future harness adapters. Only Hermes is implemented in v0.3.

Same task / model / environment across adapters is postponed until TraceV1
and the canary are stable. Do not treat these stubs as a leaderboard.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentAdapter(ABC):
    name: str

    @abstractmethod
    def run(self, task: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
        """Return a TraceV1 dict."""


class HermesAdapter(AgentAdapter):
    name = "hermes"

    def run(self, task: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
        from hermes_eval.cli import run_fixture
        from hermes_eval.trace.rescore import emit_trace
        import json
        from pathlib import Path

        fixture = task.get("fixture")
        ref = env.get("hermes_sha") or env.get("ref")
        if not fixture or not ref:
            raise ValueError("HermesAdapter requires task.fixture and env.hermes_sha")
        path = run_fixture(fixture, str(ref))
        result = json.loads(Path(path).read_text(encoding="utf-8"))
        return emit_trace(result)


class PiAdapter(AgentAdapter):
    name = "pi"

    def run(self, task: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("PiAdapter is postponed until after v0.6")


class OpenClawAdapter(AgentAdapter):
    name = "openclaw"

    def run(self, task: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("OpenClawAdapter is postponed until after v0.6")


class CodexAdapter(AgentAdapter):
    name = "codex"

    def run(self, task: dict[str, Any], env: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("CodexAdapter is postponed until after v0.6")
