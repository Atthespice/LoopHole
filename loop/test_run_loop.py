"""Unit tests for the attacking loop.

All tests use a fake in-process model -- no anthropic package, no API key, no
network. They exercise the loop's contract: budget, event shapes, wire format,
adaptation from history, and refusal handling (CONTRACT.md Gate 3).
"""

from __future__ import annotations

import json

import pytest

from shared.types import Attempt, GuardCase
from loop.model import ModelRefusal, Proposal, build_prompt, parse_proposal
from loop.run_loop import _run_loop, run_loop


# --- fakes / fixtures ------------------------------------------------------


def _blocks_short(value: str) -> bool:
    """A toy guard: allows through anything longer than 3 chars.

    Deliberately trivial -- these tests check the *loop*, not a real guard.
    True = allowed through, False = blocked (per shared.types.GuardCase).
    """
    return len(value) > 3


def make_case(guard=_blocks_short) -> GuardCase:
    return GuardCase(
        name="toy_case",
        description="toy guard for loop tests",
        guard=guard,
        oracle=lambda s: True,  # never used by the loop; present to satisfy the shape
        safe_inputs=["ok"],
    )


class ScriptedModel:
    """Yields a fixed list of proposals, one per propose() call."""

    def __init__(self, proposals):
        self._proposals = list(proposals)
        self.calls = 0
        self.histories = []

    def propose(self, case, history):
        self.histories.append(list(history))
        proposal = self._proposals[self.calls]
        self.calls += 1
        return proposal


class AdaptiveModel:
    """Returns a candidate whose length grows with the history it has seen,
    proving the loop feeds prior attempts back in."""

    def propose(self, case, history):
        return Proposal(input="x" * (len(history) + 1), reasoning=f"seen {len(history)}")


class RefusingModel:
    """Always refuses."""

    def __init__(self):
        self.calls = 0

    def propose(self, case, history):
        self.calls += 1
        raise ModelRefusal("nope")


class RefuseThenAnswerModel:
    """Refuses the first call, then answers."""

    def __init__(self):
        self.calls = 0

    def propose(self, case, history):
        self.calls += 1
        if self.calls == 1:
            raise ModelRefusal("not this time")
        return Proposal(input="passthrough", reasoning="ok")


def read_events(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --- tests -----------------------------------------------------------------


def test_public_entry_point_signature():
    import inspect

    params = list(inspect.signature(run_loop).parameters)
    assert params == ["case", "budget", "log_path"]


def test_budget_is_respected(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = ScriptedModel([Proposal(f"cand{i}") for i in range(10)])
    _run_loop(make_case(), budget=3, log_path=str(log), model=model)

    assert model.calls == 3
    attempts = [e for e in read_events(log) if e["kind"] == "attempt"]
    assert len(attempts) == 3


def test_zero_budget_writes_only_done(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = ScriptedModel([])
    _run_loop(make_case(), budget=0, log_path=str(log), model=model)

    events = read_events(log)
    assert model.calls == 0
    assert [e["kind"] for e in events] == ["done"]


def test_candidate_emitted_when_guard_allows(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    # "no" (len 2) is blocked; "yesyes" (len 6) is allowed through.
    model = ScriptedModel([Proposal("no"), Proposal("yesyes")])
    _run_loop(make_case(), budget=2, log_path=str(log), model=model)

    events = read_events(log)
    kinds = [e["kind"] for e in events]
    assert kinds == ["attempt", "attempt", "candidate", "done"]

    candidate = next(e for e in events if e["kind"] == "candidate")
    assert candidate["payload"] == {
        "case_name": "toy_case",
        "input": "yesyes",
        "attempt_index": 1,
    }


def test_attempt_payload_shape(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = ScriptedModel([Proposal("longenough", reasoning="because")])
    _run_loop(make_case(), budget=1, log_path=str(log), model=model)

    attempt = next(e for e in read_events(log) if e["kind"] == "attempt")
    assert attempt["payload"] == {
        "case_name": "toy_case",
        "input": "longenough",
        "guard_result": True,
        "reasoning": "because",
    }


def test_no_candidate_when_guard_blocks(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = ScriptedModel([Proposal("no"), Proposal("hi")])  # both len <= 3, blocked
    _run_loop(make_case(), budget=2, log_path=str(log), model=model)

    kinds = [e["kind"] for e in read_events(log)]
    assert kinds == ["attempt", "attempt", "done"]


def test_loop_feeds_history_to_model(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = ScriptedModel([Proposal("a"), Proposal("bb"), Proposal("ccc")])
    _run_loop(make_case(), budget=3, log_path=str(log), model=model)

    # Each call should see one more prior attempt than the last.
    assert [len(h) for h in model.histories] == [0, 1, 2]
    assert model.histories[2][0].input == "a"
    assert model.histories[2][1].input == "bb"


def test_loop_adapts_via_history(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    _run_loop(make_case(), budget=4, log_path=str(log), model=AdaptiveModel())

    inputs = [e["payload"]["input"] for e in read_events(log) if e["kind"] == "attempt"]
    assert inputs == ["x", "xx", "xxx", "xxxx"]


def test_all_refusals_raises(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = RefusingModel()
    with pytest.raises(ModelRefusal):
        _run_loop(make_case(), budget=3, log_path=str(log), model=model)

    assert model.calls == 3
    # Budget was still spent and the run was terminated with a done marker.
    kinds = [e["kind"] for e in read_events(log)]
    assert kinds == ["done"]


def test_partial_refusal_continues(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    model = RefuseThenAnswerModel()
    _run_loop(make_case(), budget=2, log_path=str(log), model=model)

    events = read_events(log)
    kinds = [e["kind"] for e in events]
    # First attempt refused (nothing logged), second allowed through.
    assert kinds == ["attempt", "candidate", "done"]
    assert events[1]["payload"]["attempt_index"] == 1


def test_never_uses_oracle(tmp_path):
    log = tmp_path / "toy_case.jsonl"

    def exploding_oracle(_):
        raise AssertionError("loop must not call case.oracle -- that's verdict's job")

    case = GuardCase(
        name="toy_case",
        description="d",
        guard=_blocks_short,
        oracle=exploding_oracle,
        safe_inputs=[],
    )
    _run_loop(case, budget=2, log_path=str(log), model=ScriptedModel([Proposal("longone"), Proposal("x")]))
    # No exception == oracle was never touched.


def test_every_line_is_valid_jsonl(tmp_path):
    log = tmp_path / "toy_case.jsonl"
    _run_loop(make_case(), budget=3, log_path=str(log), model=AdaptiveModel())

    with open(log, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                event = json.loads(line)
                assert "kind" in event


# --- model helper tests (no network) ---------------------------------------


def test_parse_proposal_json():
    p = parse_proposal('{"input": "abc", "reasoning": "why"}')
    assert p.input == "abc"
    assert p.reasoning == "why"


def test_parse_proposal_json_with_surrounding_prose():
    p = parse_proposal('Here you go:\n{"input": "abc", "reasoning": "why"}\nHope that helps.')
    assert p.input == "abc"
    assert p.reasoning == "why"


def test_parse_proposal_falls_back_to_raw_text():
    p = parse_proposal("just-a-raw-candidate")
    assert p.input == "just-a-raw-candidate"
    assert p.reasoning is None


def test_build_prompt_includes_history_and_case():
    case = make_case()
    history = [Attempt(case_name="toy_case", input="tried", guard_result=False, reasoning="r")]
    prompt = build_prompt(case, history)
    assert "toy_case" in prompt
    assert "tried" in prompt
    assert "blocked" in prompt


def test_build_prompt_first_turn():
    prompt = build_prompt(make_case(), [])
    assert "first candidate" in prompt.lower()
