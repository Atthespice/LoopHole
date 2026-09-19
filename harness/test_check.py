"""Tests for the bypass regression gate. No API key needed."""

from harness.check import load_known, offline_gate
import harness.cases as broken
import examples.fixed_guards as fixed


def test_recorded_bypasses_exist_for_every_case():
    known = load_known()
    for case in broken.CASES:
        assert known.get(case.name), f"no recorded bypass for {case.name}"


def test_gate_fails_on_the_broken_guards():
    known = load_known()
    failures = offline_gate(broken.CASES, known)
    # Every broken guard should still be caught by its recorded bypass.
    failed_names = {name for name, _ in failures}
    assert failed_names == {c.name for c in broken.CASES}


def test_gate_passes_on_the_fixed_guards():
    known = load_known()
    failures = offline_gate(fixed.CASES, known)
    assert failures == []


def test_fixed_guards_still_allow_their_safe_inputs():
    for case in fixed.CASES:
        for s in case.safe_inputs:
            assert case.guard(s), f"{case.name} rejected safe input {s!r}"
