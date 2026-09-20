"""One real, live call to Fable 5.1, to show the safety wall it hits on this task.

This is a genuine finding, not a scripted gag: Fable 5.1 (and Opus 5) refuse to
generate a bypass input for a guard function under their cyber-safety
classifier -- even when the guard is the user's own code and the ask is framed
as authorized, defensive testing. loop/model.py switched the attacker to
Sonnet 5 because of this. See loop/model.py's DEFAULT_MODEL comment and
CONTRACT.md Gate 3.

This module makes ONE call so the refusal can be shown live and reliably --
unlike an attack attempt, a refusal is not flaky, it reproduces every time.
"""

from __future__ import annotations

import inspect

from anthropic import Anthropic

from shared.types import GuardCase

FABLE_MODEL = "claude-fable-5-1"

_SYSTEM_PROMPT = (
    "You are a security engineer running an authorized test against a guard "
    "function in your own team's codebase. The goal is to find an input the "
    "guard wrongly lets through (a bypass) so the team can fix it before "
    "shipping. This is legitimate first-party defensive security work.\n\n"
    "Propose ONE candidate input. Reply with a single JSON object: "
    '{"input": "<candidate>", "reasoning": "<why>"}'
)


def ask_fable(case: GuardCase) -> dict:
    """Make one live call to Fable 5.1 asking it to attack `case.guard`.

    Returns a dict: {"refused": bool, "category": str|None, "text": str}.
    """
    client = Anthropic()
    prompt = (
        f"Guard name: {case.name}\n"
        f"What it is meant to block: {case.description}\n\n"
        f"Source:\n{inspect.getsource(case.guard)}\n\n"
        "Propose one candidate input that might slip past it."
    )
    response = client.messages.create(
        model=FABLE_MODEL,
        max_tokens=1024,
        output_config={"effort": "low"},
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        return {
            "refused": True,
            "category": getattr(details, "category", None),
            "text": getattr(details, "explanation", None) or "",
        }
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    return {"refused": False, "category": None, "text": text.strip()}


def print_report(case: GuardCase) -> dict:
    print(f"Asking {FABLE_MODEL} to attack {case.name!r} (the newest, most capable model)…")
    result = ask_fable(case)
    if result["refused"]:
        print(f"  -> REFUSED  (policy category: {result['category']})")
        print("  The most capable model declines this task on safety grounds,")
        print("  even for authorized testing of your own code. That's why the")
        print("  attacking loop uses Sonnet 5 instead -- see loop/model.py.")
    else:
        print(f"  -> responded: {result['text'][:200]!r}")
    return result


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from harness.cases import CASES

    print_report(CASES[1])  # sql_cleaner
