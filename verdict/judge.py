"""Owned by: verdict/ (see CONTRACT.md).

Entry point: judge(case, candidate) -> Verdict
Confirms a candidate is a real bypass via case.oracle, checks it against
case.safe_inputs to rule out false alarms, and writes a one-line fix.
"""

from shared.types import GuardCase, Candidate, Verdict


def judge(case: GuardCase, candidate: Candidate) -> Verdict:
    # TODO: run case.oracle(candidate.input); confirm it's not in
    # case.safe_inputs; write a one-line suggested_fix.
    raise NotImplementedError
