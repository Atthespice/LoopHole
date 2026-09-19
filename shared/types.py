# shared/types.py — do not edit without full team agreement.
# Canonical copy lives in CONTRACT.md. If this drifts from that file, CONTRACT.md wins.

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class GuardCase:
    """One vulnerable guard function to attack. Owned by harness/."""
    name: str                      # e.g. "path_traversal"
    description: str               # one line, plain English
    guard: Callable[[str], bool]   # True = input allowed through, False = blocked
    oracle: Callable[[str], bool]  # ground truth: True = input actually reaches
                                    # the protected resource (used to confirm a
                                    # break is real, not a false alarm)
    safe_inputs: list[str]         # known-good inputs; must never be flagged


@dataclass
class Attempt:
    """One try the loop made against a GuardCase. Owned by loop/."""
    case_name: str
    input: str
    guard_result: bool             # what the guard said: True = let it through
    reasoning: Optional[str] = None


@dataclass
class Candidate:
    """An attempt that got past the guard, not yet confirmed real. Owned by loop/."""
    case_name: str
    input: str
    attempt_index: int


@dataclass
class Verdict:
    """The ruling on a Candidate. Owned by verdict/."""
    case_name: str
    input: str
    is_real_bypass: bool           # oracle-confirmed
    explanation: str               # plain English, shown live in the demo
    suggested_fix: str             # one line
