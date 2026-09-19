"""Owned by: verdict/ (see CONTRACT.md).

Entry point: judge(case, candidate) -> Verdict

The loop says "this input got past the guard". The judge decides whether that
is a *real* break or a false alarm, without trusting anything the loop did:

  1. re-run case.guard on the input   -- the guard must actually let it through
  2. run case.oracle on the input     -- the input must actually reach the
                                         protected resource (ground truth)
  3. check case.safe_inputs           -- a known-good input can never be a break

Only when all three agree is `is_real_bypass=True`. The verdict also carries a
plain-English explanation (shown live by demo/) and a one-line suggested fix
derived from the shape of the input that got through.

Wire format: `tail_and_judge()` follows runs/<case_name>.jsonl, judges every
`candidate` event, and appends a `verdict` event for each. Stops on `done`.

Only imports from shared/. Never imports loop/ or demo/.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from dataclasses import asdict
from typing import Callable, Iterable, Optional, TextIO
from urllib.parse import unquote

from shared.types import Candidate, GuardCase, Verdict

__all__ = ["judge", "suggest_fix", "tail_and_judge", "verdict_event"]


# --------------------------------------------------------------------------- #
# Core ruling
# --------------------------------------------------------------------------- #


def _call(fn: Callable[[str], bool], value: str) -> tuple[Optional[bool], Optional[str]]:
    """Run a guard/oracle defensively. Returns (result, error). A crash is
    never treated as a pass -- it is reported and the candidate is rejected."""
    try:
        return bool(fn(value)), None
    except Exception as exc:  # noqa: BLE001 - report anything, swallow nothing
        return None, f"{type(exc).__name__}: {exc}"


def _reject(case: GuardCase, value: str, why: str, fix: str = "n/a") -> Verdict:
    return Verdict(
        case_name=case.name,
        input=value,
        is_real_bypass=False,
        explanation=why,
        suggested_fix=fix,
    )


def judge(case: GuardCase, candidate: Candidate) -> Verdict:
    """Rule on one candidate. Pure: no I/O, no model calls, deterministic."""
    value = candidate.input

    if candidate.case_name != case.name:
        return _reject(
            case, value,
            f"Candidate was logged for case {candidate.case_name!r} but judged "
            f"against {case.name!r}; refusing to rule on a mismatched case.",
        )

    guard_ok, guard_err = _call(case.guard, value)
    if guard_err is not None:
        return _reject(
            case, value,
            f"Guard crashed on this input ({guard_err}); a crash is a denial, "
            f"not a bypass.",
            fix="Make the guard fail closed: catch exceptions and return False.",
        )

    oracle_ok, oracle_err = _call(case.oracle, value)
    if oracle_err is not None:
        return _reject(
            case, value,
            f"Oracle crashed on this input ({oracle_err}); cannot confirm the "
            f"input reaches the protected resource.",
        )

    if not guard_ok:
        return _reject(
            case, value,
            "Re-running the guard blocked this input; the loop's candidate does "
            "not reproduce.",
        )

    if value in case.safe_inputs:
        note = (
            " (Note: the oracle also flags it, so the harness's safe_inputs and "
            "oracle disagree; report to harness/.)"
            if oracle_ok else ""
        )
        return _reject(
            case, value,
            "Input is in the case's safe_inputs list, so letting it through is "
            "the intended behaviour, not a bypass." + note,
        )

    if not oracle_ok:
        return _reject(
            case, value,
            "Guard let it through but the oracle says it never reaches the "
            "protected resource; false alarm.",
        )

    return Verdict(
        case_name=case.name,
        input=value,
        is_real_bypass=True,
        explanation=_explain_real(case, value),
        suggested_fix=suggest_fix(case, value),
    )


def _explain_real(case: GuardCase, value: str) -> str:
    traits = ", ".join(_traits(value)) or "no unusual characters"
    return (
        f"Confirmed real bypass of {case.name}: the guard allowed {value!r} and the "
        f"oracle confirms it reaches the protected resource. Input traits: {traits}."
    )


# --------------------------------------------------------------------------- #
# Suggested fix -- one line, derived from what the input looks like
# --------------------------------------------------------------------------- #

_PCT_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_SQL_RE = re.compile(
    r"(--|;|'|\"|/\*|\*/|\bunion\b|\bselect\b|\bor\b\s+\d+\s*=\s*\d+)", re.I
)
_HOST_TRICK_RE = re.compile(r"@|//|:\d+|\.$")


def _traits(value: str) -> list[str]:
    t: list[str] = []
    if "\x00" in value:
        t.append("NUL byte")
    if _PCT_RE.search(value):
        t.append("percent-encoding")
        if _PCT_RE.search(unquote(value)):
            t.append("double-encoding")
    if any(ord(c) > 127 for c in value):
        t.append("non-ASCII")
        if unicodedata.normalize("NFKC", value) != value:
            t.append("Unicode-normalizes to something else")
    if any(c < " " and c != "\x00" for c in value) or "\x7f" in value:
        t.append("control characters")
    if value != value.strip():
        t.append("leading/trailing whitespace")
    if "\\" in value:
        t.append("backslash")
    if ".." in value or value.startswith("/") or ":/" in value:
        t.append("path traversal shape")
    if value != value.lower() and value.lower() != value.upper():
        t.append("mixed case")
    if _SQL_RE.search(value):
        t.append("SQL metacharacters")
    if _HOST_TRICK_RE.search(value):
        t.append("URL/host trick")
    return t


def suggest_fix(case: GuardCase, value: str) -> str:
    """One-line fix. Heuristic on the input's shape first, then on the case
    name/description, then a generic fallback. Deterministic and offline."""
    traits = set(_traits(value))
    blob = f"{case.name} {case.description}".lower()

    if "NUL byte" in traits:
        return "Reject any input containing a NUL byte before running other checks."
    if "double-encoding" in traits:
        return ("Percent-decode repeatedly until the value stops changing, "
                "then validate the decoded form.")
    if "percent-encoding" in traits:
        return "Percent-decode the input first and validate the decoded value, not the raw string."
    if "Unicode-normalizes to something else" in traits:
        return ("Apply unicodedata.normalize('NFKC', s) before validating, "
                "or reject non-ASCII outright.")
    if "non-ASCII" in traits:
        return "Reject non-ASCII characters before validating, or normalize with NFKC and re-check."
    if "control characters" in traits or "leading/trailing whitespace" in traits:
        return "Strip and reject whitespace/control characters before validating."
    if "backslash" in traits:
        return "Normalize backslashes to forward slashes before the path check."
    if "path traversal shape" in traits or "traversal" in blob or "path" in blob:
        return ("Resolve to a canonical real path (os.path.realpath) and require "
                "it to start with the allowed root.")
    if "SQL metacharacters" in traits or any(k in blob for k in ("sql", "db", "database", "query")):
        return "Use parameterized queries; never build SQL by cleaning strings."
    if "URL/host trick" in traits or any(
        k in blob for k in ("allowlist", "whitelist", "host", "domain", "url")
    ):
        return ("Parse the URL and compare the exact hostname against the "
                "allowlist, not a prefix or substring.")
    if "mixed case" in traits:
        return "Casefold the input before comparing, and compare after every normalization step."
    return "Validate the canonical form against a strict allowlist instead of denying known-bad patterns."


# --------------------------------------------------------------------------- #
# Wire format: tail runs/<case_name>.jsonl, append verdict events
# --------------------------------------------------------------------------- #


def verdict_event(v: Verdict) -> dict:
    return {"kind": "verdict", "payload": asdict(v)}


def _candidate_from_payload(p: dict) -> Candidate:
    return Candidate(
        case_name=p["case_name"],
        input=p["input"],
        attempt_index=int(p.get("attempt_index", -1)),
    )


def _follow(path: str, poll: float, stop_on_done: bool) -> Iterable[dict]:
    """Yield parsed events from a JSONL file as they are appended."""
    while not os.path.exists(path):
        time.sleep(poll)
    with open(path, "r", encoding="utf-8") as fh:
        buf = ""
        while True:
            chunk = fh.readline()
            if not chunk:
                time.sleep(poll)
                continue
            buf += chunk
            if not buf.endswith("\n"):
                continue  # partial line; wait for the writer to finish it
            line, buf = buf.strip(), ""
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield ev
            if stop_on_done and ev.get("kind") == "done":
                return


def tail_and_judge(
    case: GuardCase,
    log_path: str,
    *,
    poll: float = 0.2,
    stop_on_done: bool = True,
    out: Optional[TextIO] = None,
) -> list[Verdict]:
    """Follow `log_path`, judge each `candidate` event, append a `verdict`
    event for it. Returns all verdicts issued. Candidates already judged (by
    input) are skipped so a restart doesn't double-rule.

    `out` lets tests pass a file handle; by default appends to `log_path`."""
    seen: set[str] = set()
    verdicts: list[Verdict] = []

    # Pre-scan so a restarted judge doesn't re-rule existing verdicts.
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("kind") == "verdict":
                    seen.add(ev["payload"]["input"])

    sink = out if out is not None else open(log_path, "a", encoding="utf-8")
    try:
        for ev in _follow(log_path, poll, stop_on_done):
            if ev.get("kind") != "candidate":
                continue
            cand = _candidate_from_payload(ev["payload"])
            if cand.input in seen:
                continue
            seen.add(cand.input)
            v = judge(case, cand)
            verdicts.append(v)
            sink.write(json.dumps(verdict_event(v), ensure_ascii=False) + "\n")
            sink.flush()
    finally:
        if out is None:
            sink.close()
    return verdicts


if __name__ == "__main__":
    # CLI for a live run:  python -m verdict.judge <case_name> [runs/<case_name>.jsonl]
    # A GuardCase holds callables, so it can't arrive over JSONL -- it has to
    # come from harness/, the folder that owns the cases. This is the *only*
    # place verdict/ touches another folder, and only at the CLI edge.
    import sys

    from harness.cases import CASES  # noqa: E402

    if len(sys.argv) < 2:
        sys.exit("usage: python -m verdict.judge <case_name> [log_path]")
    name = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else os.path.join("runs", f"{name}.jsonl")
    matches = [c for c in CASES if c.name == name]
    if not matches:
        sys.exit(f"no GuardCase named {name!r} in harness.cases.CASES")
    for v in tail_and_judge(matches[0], path):
        flag = "REAL BYPASS" if v.is_real_bypass else "false alarm"
        print(f"[{flag}] {v.input!r}: {v.explanation}")
        if v.is_real_bypass:
            print(f"    fix: {v.suggested_fix}")
