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
`candidate` event (one verdict per event), appends a `verdict` event for each,
and returns after `done` once every earlier candidate has a verdict. Corrupt
lines and malformed payloads are reported, never silently dropped.

Only imports from shared/. Never imports loop/, demo/, or harness/; the CLI
has the GuardCase injected via --cases MODULE:ATTR.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional, TextIO
from urllib.parse import unquote

from shared.types import Candidate, GuardCase, Verdict

__all__ = [
    "judge", "suggest_fix", "tail_and_judge", "verdict_event",
    "TailResult", "TailError", "load_case", "main",
]


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
#
# Completion protocol (verdict/'s reading of CONTRACT.md; see README):
#   * loop/ writes `done` when it has finished *generating*. Verdicts for the
#     last candidates land after it.
#   * The tailer stops only after it has seen `done` AND ruled on every
#     candidate that came before it, so when it returns, every candidate
#     event in the file has a matching verdict event.
#   * A consumer (demo/) must therefore not treat `done` as "nothing more will
#     be written"; it should keep tailing until #verdicts == #candidates.
#
# Error handling: nothing is silently dropped. A line that is not valid JSON,
# or a candidate whose payload is malformed, is reported through `on_error`
# (stderr by default) and collected in TailResult.errors. A malformed
# candidate that still carries a usable `input` gets a not-a-bypass verdict so
# the wire never shows a candidate with no ruling.


@dataclass
class TailError:
    """One problem seen while tailing. `line_no` is 1-based in the log file."""
    line_no: int
    reason: str
    raw: str


@dataclass
class TailResult:
    verdicts: list[Verdict] = field(default_factory=list)
    errors: list[TailError] = field(default_factory=list)


def verdict_event(v: Verdict) -> dict:
    return {"kind": "verdict", "payload": asdict(v)}


class MalformedCandidate(ValueError):
    pass


def _candidate_from_payload(p: object) -> Candidate:
    """Strict: raises MalformedCandidate naming exactly what is wrong."""
    if not isinstance(p, dict):
        raise MalformedCandidate(f"payload is {type(p).__name__}, expected object")
    problems = []
    case_name = p.get("case_name")
    if not isinstance(case_name, str):
        problems.append("case_name missing or not a string")
    value = p.get("input")
    if not isinstance(value, str):
        problems.append("input missing or not a string")
    idx = p.get("attempt_index")
    if not isinstance(idx, int) or isinstance(idx, bool):
        problems.append("attempt_index missing or not an integer")
    if problems:
        raise MalformedCandidate("; ".join(problems))
    return Candidate(case_name=case_name, input=value, attempt_index=idx)


def _default_on_error(err: TailError) -> None:
    print(f"[verdict] line {err.line_no}: {err.reason}: {err.raw[:200]!r}", file=sys.stderr)


def _follow(path: str, poll: float) -> Iterable[tuple[int, str]]:
    """Yield (line_no, raw_line) for each complete line appended to the file."""
    while not os.path.exists(path):
        time.sleep(poll)
    line_no = 0
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
            line_no += 1
            line, buf = buf.rstrip("\r\n"), ""
            if line.strip():
                yield line_no, line


def _existing_verdict_counts(log_path: str) -> Counter:
    """How many verdicts already exist per input (for restart idempotency)."""
    counts: Counter = Counter()
    if not os.path.exists(log_path):
        return counts
    with open(log_path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue  # reported by the main pass
            if isinstance(ev, dict) and ev.get("kind") == "verdict":
                p = ev.get("payload")
                if isinstance(p, dict) and isinstance(p.get("input"), str):
                    counts[p["input"]] += 1
    return counts


def tail_and_judge(
    case: GuardCase,
    log_path: str,
    *,
    poll: float = 0.2,
    out: Optional[TextIO] = None,
    on_error: Callable[[TailError], None] = _default_on_error,
) -> TailResult:
    """Follow `log_path`, judge every `candidate` event, append a `verdict`
    event for each one. Returns after `done` once every candidate before it
    has a verdict.

    One verdict per candidate *event*: the same input from two different
    attempts gets two verdicts. Restart idempotency: on start, existing
    verdicts are counted per input, and that many candidate events for that
    input are skipped, so re-running the judge never double-rules and never
    collapses separate attempts.

    `out` lets tests pass a file handle; by default appends to `log_path`."""
    already = _existing_verdict_counts(log_path)
    result = TailResult()

    def report(line_no: int, reason: str, raw: str) -> None:
        err = TailError(line_no=line_no, reason=reason, raw=raw)
        result.errors.append(err)
        on_error(err)

    def emit(v: Verdict) -> None:
        result.verdicts.append(v)
        sink.write(json.dumps(verdict_event(v), ensure_ascii=False) + "\n")
        sink.flush()

    sink = out if out is not None else open(log_path, "a", encoding="utf-8")
    try:
        for line_no, raw in _follow(log_path, poll):
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError as exc:
                report(line_no, f"corrupt JSON ({exc.msg})", raw)
                continue
            if not isinstance(ev, dict) or not isinstance(ev.get("kind"), str):
                report(line_no, "event is not an object with a string 'kind'", raw)
                continue

            kind = ev["kind"]
            if kind == "done":
                return result
            if kind != "candidate":
                continue

            payload = ev.get("payload")
            try:
                cand = _candidate_from_payload(payload)
            except MalformedCandidate as exc:
                report(line_no, f"malformed candidate payload: {exc}", raw)
                # Still rule on it if there is a usable input, so no candidate
                # is left without a verdict on the wire.
                value = payload.get("input") if isinstance(payload, dict) else None
                if isinstance(value, str):
                    emit(Verdict(
                        case_name=case.name, input=value, is_real_bypass=False,
                        explanation=f"Malformed candidate event (line {line_no}: {exc}); "
                                    f"not judged as a bypass.",
                        suggested_fix="n/a",
                    ))
                continue

            if already[cand.input] > 0:
                already[cand.input] -= 1  # ruled on in a previous run
                continue

            emit(judge(case, cand))
    finally:
        if out is None:
            sink.close()
    return result


# --------------------------------------------------------------------------- #
# CLI -- the GuardCase is injected, never imported from another folder
# --------------------------------------------------------------------------- #


def load_case(spec: str, case_name: str) -> GuardCase:
    """Resolve `module.path:ATTR` to a GuardCase. ATTR may be a GuardCase, or
    a list/dict of them, in which case `case_name` selects one. verdict/ has
    no knowledge of which module that is; the caller supplies it."""
    if ":" not in spec:
        raise SystemExit(f"--cases must look like module.path:ATTR, got {spec!r}")
    mod_name, attr = spec.rsplit(":", 1)
    obj = getattr(importlib.import_module(mod_name), attr)
    if isinstance(obj, GuardCase):
        found = [obj] if obj.name == case_name else []
    elif isinstance(obj, dict):
        found = [obj[case_name]] if case_name in obj else []
    else:
        found = [c for c in obj if isinstance(c, GuardCase) and c.name == case_name]
    if not found:
        raise SystemExit(f"no GuardCase named {case_name!r} in {spec}")
    return found[0]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m verdict.judge",
        description="Tail a run log, append a verdict event for every candidate.",
    )
    parser.add_argument("case_name", help="GuardCase.name to judge against")
    parser.add_argument(
        "--cases", required=True, metavar="MODULE:ATTR",
        help="where to load the GuardCase from, e.g. harness.cases:CASES",
    )
    parser.add_argument("--log", help="defaults to runs/<case_name>.jsonl")
    args = parser.parse_args(argv)

    case = load_case(args.cases, args.case_name)
    log = args.log or os.path.join("runs", f"{args.case_name}.jsonl")
    res = tail_and_judge(case, log)
    for v in res.verdicts:
        flag = "REAL BYPASS" if v.is_real_bypass else "false alarm"
        print(f"[{flag}] {v.input!r}: {v.explanation}")
        if v.is_real_bypass:
            print(f"    fix: {v.suggested_fix}")
    if res.errors:
        print(f"[verdict] {len(res.errors)} malformed line(s) reported above", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
