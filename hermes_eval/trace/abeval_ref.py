"""Frozen copy of hermes-toolperf-evals abeval.ab_eval.score_run (2026-08-06).

Do not 'improve' this. Gate 1 compares TraceV1 metrics to this function.
Source: NousResearch/hermes-toolperf-evals abeval/ab_eval.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def score_run(atof: Path) -> dict | None:
    llm = tools = errs = retries = 0
    result_bytes = 0
    last_err_tool = None
    if not atof.exists():
        return None
    for line in atof.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        k, c, sc = ev.get("kind"), ev.get("category"), ev.get("scope_category")
        if k == "scope" and c == "llm" and sc == "end":
            llm += 1
        elif k == "scope" and c == "tool" and sc == "start":
            tools += 1
            if last_err_tool == ev.get("name"):
                retries += 1
        elif k == "scope" and c == "tool" and sc == "end":
            d = ev.get("data")
            ds = d if isinstance(d, str) else json.dumps(d or "")
            result_bytes += len(ds)
            is_err = ev.get("metadata", {}).get("status") not in (None, "ok")
            if not is_err:
                if re.search(r'"error":\s*"(?!null)', ds[:1500]) or re.search(
                    r'"exit_code":\s*[1-9-]', ds[:200]
                ):
                    is_err = True
            if is_err:
                errs += 1
                last_err_tool = ev.get("name")
            else:
                last_err_tool = None
    return {
        "llm": llm,
        "tools": tools,
        "errs": errs,
        "retries": retries,
        "kb": result_bytes // 1024,
        "tool_result_bytes": result_bytes,
    }
