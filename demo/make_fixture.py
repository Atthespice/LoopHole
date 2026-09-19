"""Owned by: demo/ (see CONTRACT.md).

Builds demo/fixtures/<case_name>.jsonl -- a contract-shaped run log used to build
and rehearse the demo before loop/ and verdict/ exist.

Nothing in the fixture is hand-asserted. Each attempt is run through the real
broken guard in demo/guards.py, and each candidate is ruled on by a local oracle
that answers the only question that matters: did this input actually land
outside the safe root? So `guard_result` and `is_real_bypass` in the fixture are
both true statements about that guard, not decoration. Edit the guard, re-run
this, and the story follows.

    python demo/make_fixture.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guards import FIXED_GUARDS, SAFE_ROOT, _resolve  # noqa: E402

CASE = "path_traversal"

# (input, reasoning, is_an_attack)
# is_an_attack=False marks a baseline probe -- allowed on purpose, never raised
# as a candidate, because the loop knows it was not trying to break anything.
ATTEMPTS: list[tuple[str, str, bool]] = [
    ("index.html", "baseline: confirm a normal request is allowed", False),
    ("docs/readme.txt", "baseline: a nested normal request", False),
    ("../../../etc/passwd", "the obvious climb-out, to see what gets rejected", True),
    ("....//....//etc/passwd", "doubled dots, in case '..' is stripped once", True),
    ("/etc/passwd", "absolute path, in case the join is naive", True),
    ("..%2f..%2fetc%2fpasswd", "percent-encoded separators, in case decoding happens later", True),
    ("../", "bare parent, to find where the boundary is drawn", True),
    ("./../../srv/app/public/../secrets.env", "climb out through a long detour", True),
    ("../public_backup/id_rsa",
     "the prefix test has no trailing separator — a sibling directory whose name "
     "merely starts with the safe root should satisfy it while living outside", True),
]


def oracle(path: str) -> bool:
    """Ground truth: does this input actually reach outside the safe root?

    This mirrors what harness/ owns as GuardCase.oracle. It exists here only so
    the fixture can be generated truthfully.
    """
    resolved = _resolve(path)
    return not (resolved == SAFE_ROOT or resolved.startswith(SAFE_ROOT + "/"))


REAL_EXPLANATION = (
    "The guard resolves the path correctly, then asks whether the result "
    f"startswith({SAFE_ROOT!r}) — with no trailing separator. "
    f"{_resolve('../public_backup/id_rsa')!r} is not inside the safe root, but it "
    "does start with that string, so the check passes and the read escapes."
)
REAL_FIX = (
    "Compare against SAFE_ROOT + os.sep (or use os.path.commonpath), not a bare prefix."
)
FALSE_ALARM_EXPLANATION = (
    "Got past the guard, but it never left the safe root — it resolves to "
    "{resolved!r}, which is inside. Not a bypass."
)


def build(path: str) -> None:
    guard = FIXED_GUARDS[CASE].broken
    lines: list[dict] = []

    for index, (value, reasoning, is_attack) in enumerate(ATTEMPTS, start=1):
        allowed = bool(guard(value))
        lines.append({
            "kind": "attempt",
            "payload": {
                "case_name": CASE,
                "input": value,
                "guard_result": allowed,
                "reasoning": reasoning,
            },
        })

        if not (allowed and is_attack):
            continue

        lines.append({
            "kind": "candidate",
            "payload": {"case_name": CASE, "input": value, "attempt_index": index},
        })

        escaped = oracle(value)
        lines.append({
            "kind": "verdict",
            "payload": {
                "case_name": CASE,
                "input": value,
                "is_real_bypass": escaped,
                "explanation": REAL_EXPLANATION if escaped else
                    FALSE_ALARM_EXPLANATION.format(resolved=_resolve(value)),
                "suggested_fix": REAL_FIX if escaped else "",
            },
        })

        if escaped:
            break  # the loop stops at the first confirmed break

    lines.append({"kind": "done"})

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")

    kinds: dict[str, int] = {}
    for line in lines:
        kinds[line["kind"]] = kinds.get(line["kind"], 0) + 1
    real = sum(
        1 for l in lines
        if l["kind"] == "verdict" and l["payload"]["is_real_bypass"]
    )
    print(f"wrote {path}")
    print(f"  {len(lines)} events {kinds}, {real} confirmed bypass")
    if real != 1:
        print("  WARNING: fixture should contain exactly one confirmed bypass")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    build(os.path.join(here, "fixtures", f"{CASE}.jsonl"))
