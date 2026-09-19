"""Owned by: loop/ (see CONTRACT.md).

Entry point: run_loop(case, budget, log_path) -> None
Appends "attempt" and "candidate" events to runs/<case_name>.jsonl as it goes,
then a terminal "done" event marking the end of generation.
Does NOT decide whether a candidate is a real bypass -- that's verdict/'s job.

The loop is generate -> run -> observe -> mutate:
  1. ask the model for a candidate input (given everything tried so far),
  2. run it against case.guard,
  3. record the attempt (and a candidate if the guard let it through),
  4. feed the growing history back into the next request so the model adapts.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Optional

from shared.types import Attempt, Candidate, GuardCase

from loop.model import AnthropicAttackModel, AttackModel, ModelRefusal


def _append_event(log_path: str, kind: str, payload: Optional[dict] = None) -> None:
    """Append one JSONL event, per the CONTRACT.md wire format."""
    event: dict = {"kind": kind}
    if payload is not None:
        event["payload"] = payload
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def run_loop(case: GuardCase, budget: int, log_path: str) -> None:
    """Run the attacking loop against ``case`` for up to ``budget`` attempts.

    Public entry point per CONTRACT.md. Uses the real anthropic-backed model;
    tests drive ``_run_loop`` directly with a fake model.
    """
    _run_loop(case, budget, log_path, model=AnthropicAttackModel())


def _run_loop(case: GuardCase, budget: int, log_path: str, model: AttackModel) -> None:
    """Loop body with an injectable model, so tests need no live API."""
    history: list[Attempt] = []
    attempts_made = 0
    refusals = 0

    for index in range(max(0, budget)):
        try:
            proposal = model.propose(case, history)
        except ModelRefusal as exc:
            # Do not swallow refusals as "no bypass found" (CONTRACT.md Gate 3).
            # Surface each one, keep spending budget, and fail loudly at the end
            # if the model never produced a single real attempt.
            refusals += 1
            print(f"[loop] attempt {index}: model refused: {exc}", file=sys.stderr)
            continue

        guard_result = case.guard(proposal.input)
        attempt = Attempt(
            case_name=case.name,
            input=proposal.input,
            guard_result=guard_result,
            reasoning=proposal.reasoning,
        )
        _append_event(log_path, "attempt", asdict(attempt))
        history.append(attempt)
        attempts_made += 1

        # guard_result True == the input was allowed through: a candidate bypass.
        # Whether it's a *real* break is verdict/'s call, not ours.
        if guard_result:
            candidate = Candidate(
                case_name=case.name,
                input=proposal.input,
                attempt_index=index,
            )
            _append_event(log_path, "candidate", asdict(candidate))

    _append_event(log_path, "done")

    if budget > 0 and attempts_made == 0 and refusals > 0:
        raise ModelRefusal(
            f"model refused on all {refusals} attempt(s) for case {case.name!r}; "
            "no candidates were generated (see CONTRACT.md Gate 3)"
        )
