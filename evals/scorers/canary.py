"""Interpret current-SHA canary results without false regression claims."""

from __future__ import annotations

from typing import Any

from hermes_eval.fixtureload import load_fixture
from hermes_eval.gitutil import is_ancestor


def interpret_canary(
    *,
    fixture: str,
    current_sha: str,
    success: bool,
) -> dict[str, Any]:
    spec = load_fixture(fixture)
    known_good = spec.get("known_good")
    known_bad = spec.get("known_bad")
    ancestor = is_ancestor(known_good, current_sha) if known_good else None
    if ancestor is True:
        if success:
            status = "PASS"
            reason = "known_good is an ancestor of this SHA; invariant holds"
        else:
            status = "REGRESSION"
            reason = (
                "known_good is an ancestor of this SHA but the fixture failed. "
                "This is the only status that may be called a regression."
            )
    elif ancestor is False:
        if success:
            status = "PASS_WITHOUT_FIX_SHA"
            reason = (
                "known_good is not an ancestor; current still satisfies the "
                "invariant (equivalent code may have landed, or the SUT never "
                "had this bug). Not a claim that the named fix SHA merged."
            )
        else:
            status = "FIX_NOT_ON_THIS_SHA"
            reason = (
                "known_good is not an ancestor. Failure is expected until that "
                "fix (or an equivalent) lands. Not a regression vs current main."
            )
    else:
        status = "INDETERMINATE"
        reason = "could not decide ancestry between known_good and current SHA"
    return {
        "fixture": fixture,
        "current_sha": current_sha,
        "known_bad": known_bad,
        "known_good": known_good,
        "known_good_is_ancestor": ancestor,
        "fixture_success": success,
        "status": status,
        "reason": reason,
    }
