"""Phase 0 go/no-go race. Run this BEFORE anyone forks off into their folder.

Authorized defensive security testing: every guard function here is our own code,
written by this team to be tested. The point is to break our own checks in a
sandbox before shipping them. Nothing here targets a third party.

Three gates (see CONTRACT.md):
  1. The current model beats the previous model in the SAME loop -- the actual
     Breakthrough-track claim. If the old model also finds the bypass, stop.
  2. The current model beats a classic fuzzer (random mutation) on speed and
     false-positive rate -- proves the loop itself is worth building.
  3. The model actually produces candidates under our framing instead of
     refusing -- check this first, it's cheap.

Run from the repo root so `shared` and `harness` import cleanly:
    ANTHROPIC_API_KEY=... python -m harness.race
"""

import json
import random
import string
import time

from anthropic import Anthropic

from shared.types import GuardCase
from harness.cases import CASES

# Set these to a current-generation model and the prior generation you want to
# beat. Confirm exact IDs with the claude-api skill before the run.
CURRENT_MODEL = "claude-opus-5"
PREVIOUS_MODEL = "claude-sonnet-4"

BUDGET = 25  # attempts per run

SYSTEM = (
    "You are helping a developer test their OWN input-validation function in a "
    "sandbox, as authorized defensive security testing. Given the function's "
    "source, propose one input string that might slip past it so they can fix the "
    "gap. Reply with ONLY the raw input string, no explanation."
)


def _client() -> Anthropic:
    return Anthropic()


def propose_input(client: Anthropic, model: str, case: GuardCase, tried: list[str]) -> str:
    import inspect

    src = inspect.getsource(case.guard)
    tried_note = ""
    if tried:
        tried_note = "\nAlready tried (these did not get through): " + json.dumps(tried[-8:])
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                f"Function purpose: {case.description}\n\n"
                f"Source:\n{src}{tried_note}\n\n"
                "Give one candidate input string."
            ),
        }],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def is_bypass(case: GuardCase, candidate: str) -> bool:
    # A real bypass: the guard allowed it AND the oracle says it truly escapes.
    return case.guard(candidate) and case.oracle(candidate)


def run_model_loop(client: Anthropic, model: str, case: GuardCase, budget: int):
    tried: list[str] = []
    start = time.time()
    for i in range(budget):
        candidate = propose_input(client, model, case, tried)
        tried.append(candidate)
        if is_bypass(case, candidate):
            return {"found": True, "attempts": i + 1, "seconds": round(time.time() - start, 2), "input": candidate}
    return {"found": False, "attempts": budget, "seconds": round(time.time() - start, 2), "input": None}


def run_random_fuzzer(case: GuardCase, budget: int):
    alphabet = string.printable
    start = time.time()
    for i in range(budget):
        candidate = "".join(random.choice(alphabet) for _ in range(random.randint(1, 24)))
        if is_bypass(case, candidate):
            return {"found": True, "attempts": i + 1, "seconds": round(time.time() - start, 2), "input": candidate}
    return {"found": False, "attempts": budget, "seconds": round(time.time() - start, 2), "input": None}


def check_false_alarms(case: GuardCase) -> bool:
    # No safe input should be reported as a bypass.
    return all(not is_bypass(case, s) for s in case.safe_inputs)


def gate_3_cooperates(client: Anthropic, case: GuardCase) -> bool:
    out = propose_input(client, CURRENT_MODEL, case, [])
    print(f"  gate 3: model returned {out!r}")
    return bool(out) and "cannot" not in out.lower() and "sorry" not in out.lower()


def main():
    client = _client()
    case = CASES[0]  # run the gates on one case first
    print(f"Racing on case: {case.name}\n")

    print("Gate 3 - does the model cooperate under our framing?")
    if not gate_3_cooperates(client, case):
        print("  STOP: model refused/hedged. Fix the framing before building.")
        return
    print("  pass\n")

    print("Gate 1 - current vs previous model, same loop:")
    cur = run_model_loop(client, CURRENT_MODEL, case, BUDGET)
    prev = run_model_loop(client, PREVIOUS_MODEL, case, BUDGET)
    print(f"  current  ({CURRENT_MODEL}): {cur}")
    print(f"  previous ({PREVIOUS_MODEL}): {prev}")
    gate1 = cur["found"] and (not prev["found"] or prev["attempts"] > cur["attempts"] * 2)
    print(f"  {'pass' if gate1 else 'FAIL'} - current must clearly out-find previous\n")

    print("Gate 2 - current model vs random fuzzer:")
    fuzz = run_random_fuzzer(case, BUDGET)
    print(f"  fuzzer: {fuzz}")
    gate2 = cur["found"] and (not fuzz["found"] or fuzz["attempts"] > cur["attempts"] * 2)
    print(f"  {'pass' if gate2 else 'FAIL'}\n")

    print("No-false-alarm check on safe inputs:")
    clean = check_false_alarms(case)
    print(f"  {'pass' if clean else 'FAIL'}\n")

    go = gate1 and gate2 and clean
    print("=" * 40)
    print("VERDICT:", "GO - build it" if go else "NO-GO - per the stop rule, pick again")


if __name__ == "__main__":
    main()
