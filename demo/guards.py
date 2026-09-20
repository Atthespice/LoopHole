"""Owned by: demo/ (see CONTRACT.md).

Local mirrors of the guard functions that harness/ owns.

WHY THIS FILE EXISTS
--------------------
CONTRACT.md asks demo/ to do two things that pull against each other:

  1. "re-runs the guard with the fix applied to show it holds"
  2. "Must not call loop/ or verdict/ code directly -- read the log file only"

The run log carries `suggested_fix` as a one-line *string* (shared/types.py), not
as anything executable, so rule 1 cannot be satisfied from the log alone. Rather
than reach into another folder's code and break the isolation that lets demo/ be
built before the others exist, demo/ keeps its own small registry here.

THIS IS A MIRROR, NOT THE SOURCE OF TRUTH. harness/ owns the real guards. If a
guard changes there, this file must be re-synced by hand. Everything here is used
for one thing only: the closing "and now it holds" panel. Nothing in the attack
path reads it.

Unregistered cases degrade gracefully -- the demo still shows the confirmed
bypass and the suggested fix, it just cannot run the live re-verification.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class FixedGuard:
    """A before/after pair for one guard case, plus inputs that must keep working."""

    case_name: str
    broken: Callable[[str], bool]   # True = input allowed through (matches GuardCase.guard)
    fixed: Callable[[str], bool]    # same signature, with the suggested fix applied
    safe_inputs: list[str] = field(default_factory=list)
    fix_summary: str = ""           # one line, shown if the log's suggested_fix is missing


# --------------------------------------------------------------------------
# FIXTURE CASE -- replace once harness/ fills in CONTRACT.md section 0.
#
# Hero-case rule (CONTRACT.md Phase 0): the bug must be self-constructed, not a
# textbook cheat-sheet entry. `../../../etc/passwd` and `%2e%2e%2f` are banned
# because every model already knows them.
#
# The bug here is a prefix-anchoring mistake, not a ".." filter miss: the guard
# normalises the path correctly and then asks `startswith(SAFE_ROOT)` WITHOUT a
# trailing separator. So a sibling directory whose name merely begins with the
# safe root's name -- /srv/app/public_backup -- satisfies the check while living
# completely outside the safe root. Blind ".." fuzzing does not find this; you
# have to reason about this specific guard's comparison and then guess a real
# sibling directory name.
# --------------------------------------------------------------------------

SAFE_ROOT = "/srv/app/public"


def _resolve(path: str) -> str:
    """Where this path actually lands once the app joins it to the safe root."""
    return posixpath.normpath(posixpath.join(SAFE_ROOT, path))


def _path_guard_broken(path: str) -> bool:
    return _resolve(path).startswith(SAFE_ROOT)


def _path_guard_fixed(path: str) -> bool:
    resolved = _resolve(path)
    return resolved == SAFE_ROOT or resolved.startswith(SAFE_ROOT + "/")


def _sql_cleaner_broken(value: str) -> bool:
    low = value.lower()
    if "'" in value or ";" in value:
        return False
    if " or " in low:  # only catches a single ASCII space on each side
        return False
    return True


def _sql_cleaner_fixed(value: str) -> bool:
    # Value goes into a numeric WHERE clause, so only allow integers.
    return value.strip().isdigit()


FIXED_GUARDS: dict[str, FixedGuard] = {
    "path_traversal": FixedGuard(
        case_name="path_traversal",
        broken=_path_guard_broken,
        fixed=_path_guard_fixed,
        safe_inputs=[
            "index.html",
            "./index.html",
            "docs/readme.txt",
            "assets/img/logo.png",
            "deeply/nested/but/fine.css",
        ],
        fix_summary="Compare against SAFE_ROOT + os.sep, not the bare prefix.",
    ),
    "sql_cleaner": FixedGuard(
        case_name="sql_cleaner",
        broken=_sql_cleaner_broken,
        fixed=_sql_cleaner_fixed,
        safe_inputs=["1", "42", "0"],
        fix_summary="Reject non-numeric input; only allow integers for a numeric WHERE clause.",
    ),
}


# --------------------------------------------------------------------------
# Verification -- what the closing panel calls.
# --------------------------------------------------------------------------


@dataclass
class FixCheck:
    """Result of re-running a case's guard with the fix applied."""

    available: bool                  # False = no local mirror for this case
    case_name: str = ""
    bypass_input: str = ""
    broke_before: bool = False       # did the bypass get through the ORIGINAL guard?
    blocked_after: bool = False      # is it blocked by the FIXED guard?
    safe_results: list[tuple[str, bool]] = field(default_factory=list)
    fix_summary: str = ""
    reason: str = ""                 # why unavailable, when available is False

    @property
    def safe_inputs_ok(self) -> bool:
        """The fix must not break normal traffic -- that is half the claim."""
        return all(ok for _, ok in self.safe_results)

    @property
    def holds(self) -> bool:
        """The full claim: it broke before, it is blocked now, nothing else broke."""
        return self.broke_before and self.blocked_after and self.safe_inputs_ok


def verify_fix(case_name: str, bypass_input: str) -> FixCheck:
    """Replay a confirmed bypass through the original and the fixed guard.

    Never raises: a demo that crashes on stage is worse than one that says
    "not registered". A guard that throws on the input is treated as blocking,
    which is the honest reading -- the input did not reach the resource.
    """
    entry = FIXED_GUARDS.get(case_name)
    if entry is None:
        return FixCheck(
            available=False,
            case_name=case_name,
            bypass_input=bypass_input,
            reason=f"no local fixed-guard mirror registered for {case_name!r}",
        )

    def call(fn: Callable[[str], bool], value: str) -> bool:
        try:
            return bool(fn(value))
        except Exception:
            return False

    return FixCheck(
        available=True,
        case_name=case_name,
        bypass_input=bypass_input,
        broke_before=call(entry.broken, bypass_input),
        blocked_after=not call(entry.fixed, bypass_input),
        safe_results=[(s, call(entry.fixed, s)) for s in entry.safe_inputs],
        fix_summary=entry.fix_summary,
    )
