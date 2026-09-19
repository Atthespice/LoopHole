"""Owned by: loop/ (see CONTRACT.md).

Entry point: run_loop(case, budget, log_path) -> None
Appends "attempt" and "candidate" events to runs/<case_name>.jsonl as it goes.
Does NOT decide whether a candidate is a real bypass -- that's verdict/'s job.
"""

from shared.types import GuardCase


def run_loop(case: GuardCase, budget: int, log_path: str) -> None:
    # TODO: generate -> run -> observe -> mutate, appending Attempt/Candidate
    # events to log_path as JSON lines (see CONTRACT.md wire format).
    raise NotImplementedError
