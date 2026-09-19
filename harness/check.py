"""CI gate: fail the build if a guard still lets a known bypass through.

The insight: a live model attack is great for *finding* a bypass, but it costs
money and is non-deterministic -- a bad fit for a blocking CI gate. So the flow
is the same one used for any security bug:

    discover it once (live) -> lock it in as a regression test -> CI re-checks it
    forever, keyless and deterministic.

Two modes:
  --offline (default): re-check each guard against the bypasses already recorded
    in harness/known_bypasses.json. No API key, fast, deterministic. Exit 1 if
    any guard still lets a recorded bypass through. This is the CI gate.
  --live: actually attack the guards with the model (needs a key, costs money).
    For discovery. Add --record to append newly found bypasses to the json.

Usage:
  python -m harness.check --offline --cases examples.fixed_guards:CASES
  python -m harness.check --live --record path_guard
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys

KNOWN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_bypasses.json")


def load_cases(spec: str):
    module_name, _, attr = spec.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr or "CASES")


def load_known() -> dict:
    if not os.path.isfile(KNOWN_PATH):
        return {}
    with open(KNOWN_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def save_known(known: dict) -> None:
    with open(KNOWN_PATH, "w", encoding="utf-8") as fh:
        json.dump(known, fh, indent=2, sort_keys=True)
        fh.write("\n")


def _is_real_bypass(case, value: str) -> bool:
    try:
        return bool(case.guard(value)) and bool(case.oracle(value))
    except Exception:
        return False


def offline_gate(cases, known: dict):
    """Return a list of (case_name, input) still vulnerable to a recorded bypass."""
    failures = []
    for case in cases:
        for value in known.get(case.name, []):
            if _is_real_bypass(case, value):
                failures.append((case.name, value))
    return failures


def live_attack(cases, budget: int):
    """Attack each case with the model. Returns {case_name: [found inputs]}."""
    from loop.run_loop import run_loop
    from verdict.judge import tail_and_judge

    found: dict = {}
    os.makedirs("runs", exist_ok=True)
    for case in cases:
        log = os.path.join("runs", f"{case.name}.jsonl")
        open(log, "w").close()
        run_loop(case, budget, log)
        result = tail_and_judge(case, log)
        reals = [v.input for v in getattr(result, "verdicts", [])
                 if getattr(v, "is_real_bypass", False)]
        if reals:
            found[case.name] = sorted(set(reals))
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="LoopHole bypass gate.")
    parser.add_argument("cases", nargs="*", help="only these case names (default: all)")
    parser.add_argument("--cases", dest="spec", default="harness.cases:CASES",
                        help="MODULE:ATTR to load GuardCases from")
    parser.add_argument("--offline", action="store_true",
                        help="regression gate against known_bypasses.json (default mode)")
    parser.add_argument("--live", action="store_true", help="attack with the model (needs a key)")
    parser.add_argument("--budget", type=int, default=15)
    parser.add_argument("--record", action="store_true",
                        help="with --live, append found bypasses to known_bypasses.json")
    args = parser.parse_args(argv)

    cases = load_cases(args.spec)
    if args.cases:
        wanted = set(args.cases)
        cases = [c for c in cases if c.name in wanted]
        if not cases:
            print(f"No matching cases in {args.spec}.")
            return 2

    if args.live:
        found = live_attack(cases, args.budget)
        for name, inputs in found.items():
            for value in inputs:
                print(f"BYPASS  {name}: {value!r}")
        if args.record and found:
            known = load_known()
            for name, inputs in found.items():
                known[name] = sorted(set(known.get(name, [])) | set(inputs))
            save_known(known)
            print(f"Recorded to {os.path.relpath(KNOWN_PATH)}.")
        if found:
            print(f"\nFAIL: {sum(len(v) for v in found.values())} real bypass(es) found.")
            return 1
        print("\nOK: no bypass found within budget.")
        return 0

    # offline gate (default)
    known = load_known()
    failures = offline_gate(cases, known)
    for name, value in failures:
        print(f"REGRESSION  {name}: still allows {value!r}")
    if failures:
        print(f"\nFAIL: {len(failures)} guard(s) still vulnerable to a recorded bypass.")
        return 1
    checked = sum(len(known.get(c.name, [])) for c in cases)
    print(f"OK: {len(cases)} guard(s) block all {checked} recorded bypass(es).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
