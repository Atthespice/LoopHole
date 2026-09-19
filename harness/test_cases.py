"""Offline tests for the guard cases. No API key needed.

Verifies the two properties every GuardCase must hold before the loop touches it:
  - safe inputs raise no false alarm (guard allows AND oracle says safe)
  - the deliberate flaw is actually reachable (a known input is a real bypass)
"""

import pytest

from harness.cases import CASES


def is_bypass(case, candidate: str) -> bool:
    return case.guard(candidate) and case.oracle(candidate)


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_safe_inputs_raise_no_false_alarm(case):
    for s in case.safe_inputs:
        assert not is_bypass(case, s), f"{case.name}: safe input falsely flagged: {s!r}"


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_guard_allows_its_own_safe_inputs(case):
    for s in case.safe_inputs:
        assert case.guard(s), f"{case.name}: guard rejected a known-good input: {s!r}"


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_oracle_clears_safe_inputs(case):
    for s in case.safe_inputs:
        assert not case.oracle(s), f"{case.name}: oracle flagged a safe input: {s!r}"


# Known bypass per case. These live in the test only (kept out of the shared doc),
# proving each deliberate flaw is reachable so the loop has something to find.
KNOWN_BYPASS = {
    "path_guard": "../safe_secrets/data",
    "sql_cleaner": "1\tOR\t1=1",
    "allowlist": "https://evil-example.com/x",
}


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_deliberate_flaw_is_reachable(case):
    candidate = KNOWN_BYPASS[case.name]
    assert case.guard(candidate), f"{case.name}: guard blocked the known bypass"
    assert case.oracle(candidate), f"{case.name}: oracle did not confirm the escape"
    assert is_bypass(case, candidate)
