"""Tests for demo/. Run: python -m pytest demo/ -q

Covers the three things that would actually ruin the demo on stage:
a malformed or half-written log line taking the screen down, a hostile input
corrupting the display, and the fix verification claiming a hole is closed when
it is not.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guards  # noqa: E402
import make_fixture  # noqa: E402
import render  # noqa: E402
import tail  # noqa: E402
from render import DemoState, visible  # noqa: E402
from tail import parse_line, read_all, tail_events  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "path_traversal.jsonl")


# ---- parsing ------------------------------------------------------------

def test_parse_blank_lines_are_skipped():
    assert parse_line("") is None
    assert parse_line("   \n") is None


def test_parse_valid_event():
    event = parse_line('{"kind":"attempt","payload":{"input":"x","guard_result":true}}')
    assert event.kind == "attempt"
    assert event.payload["input"] == "x"
    assert event.payload["guard_result"] is True


def test_done_event_has_no_payload():
    assert parse_line('{"kind":"done"}').kind == tail.DONE


@pytest.mark.parametrize("line", [
    "not json at all",
    '{"kind":"attempt"',      # half-written append
    "[1, 2, 3]",              # valid json, wrong shape
    '{"payload":{}}',         # no kind
    '{"kind":"attempt","payload":"not a dict"}',
])
def test_garbage_never_raises(line):
    event = parse_line(line)
    assert event is not None
    # The only one that survives as a real event is the bad-payload case, which
    # is normalised to an empty dict rather than blowing up downstream.
    assert event.kind in (tail.MALFORMED, "attempt")
    assert isinstance(event.payload, dict)


def test_read_all_missing_file_is_empty():
    assert read_all("/nonexistent/path/nope.jsonl") == []


# ---- tailing ------------------------------------------------------------

def test_tail_waits_for_a_file_that_does_not_exist_yet(tmp_path):
    log = tmp_path / "late.jsonl"

    def write_later():
        time.sleep(0.25)
        with open(log, "w") as fh:
            fh.write('{"kind":"attempt","payload":{"input":"a","guard_result":false}}\n')
            fh.write('{"kind":"done"}\n')

    threading.Thread(target=write_later, daemon=True).start()
    events = list(tail_events(str(log), timeout=5))
    assert [e.kind for e in events] == ["attempt", "done"]


def test_tail_does_not_emit_a_half_written_line(tmp_path):
    log = tmp_path / "partial.jsonl"
    log.write_text('{"kind":"attempt","payload":{"input":"a","guard_result":false}}\n'
                   '{"kind":"attem')  # writer was interrupted mid-append

    def finish():
        time.sleep(0.3)
        with open(log, "a") as fh:
            fh.write('pt","payload":{"input":"b","guard_result":true}}\n')
            fh.write('{"kind":"done"}\n')

    threading.Thread(target=finish, daemon=True).start()
    events = list(tail_events(str(log), timeout=5))
    kinds = [e.kind for e in events]
    assert tail.MALFORMED not in kinds
    assert [e.payload.get("input") for e in events if e.kind == "attempt"] == ["a", "b"]


def test_tail_stops_on_done(tmp_path):
    log = tmp_path / "done.jsonl"
    log.write_text('{"kind":"done"}\n{"kind":"attempt","payload":{}}\n')
    assert [e.kind for e in tail_events(str(log), timeout=5)] == ["done"]


# ---- state --------------------------------------------------------------

def _state_from(path: str) -> DemoState:
    state = DemoState(static=True)
    for event in read_all(path):
        state.ingest(event)
    return state


def test_fixture_tells_the_intended_story():
    state = _state_from(FIXTURE)
    assert state.case_name == "path_traversal"
    assert state.confirmed is not None, "fixture must contain a confirmed bypass"
    assert state.confirmed["input"] == "../public_backup/id_rsa"
    assert state.n_false_alarms == 2, "the false alarms are what make verdict/ visible"
    assert state.n_malformed == 0
    assert state.done


def test_confirmed_bypass_is_marked_in_the_feed():
    state = _state_from(FIXTURE)
    winner = [r for r in state.attempts if r.input == state.confirmed["input"]]
    assert len(winner) == 1
    assert winner[0].allowed is True


def test_only_the_first_confirmed_bypass_is_kept():
    state = DemoState()
    for value in ("first", "second"):
        state.ingest(tail.Event(kind=tail.VERDICT, payload={
            "case_name": "c", "input": value, "is_real_bypass": True,
            "explanation": "", "suggested_fix": "",
        }))
    assert state.confirmed["input"] == "first"


def test_false_alarm_does_not_become_the_headline():
    state = DemoState()
    state.ingest(tail.Event(kind=tail.VERDICT, payload={
        "case_name": "c", "input": "x", "is_real_bypass": False,
        "explanation": "nope", "suggested_fix": "",
    }))
    assert state.confirmed is None
    assert state.n_false_alarms == 1


def test_attempt_history_stays_bounded():
    state = DemoState()
    for i in range(1000):
        state.ingest(tail.Event(kind=tail.ATTEMPT, payload={
            "case_name": "c", "input": f"i{i}", "guard_result": False,
        }))
    assert state.n_attempts == 1000          # the count is never lost
    assert len(state.attempts) <= 400        # the buffer is


# ---- display safety -----------------------------------------------------

@pytest.mark.parametrize("hostile", [
    "[bold red]fake markup[/]",
    "line1\nline2",
    "tab\there",
    "null\x00byte",
    "\x1b[31mansi escape\x1b[0m",
    "",
])
def test_hostile_inputs_render_as_one_visible_line(hostile):
    out = visible(hostile)
    assert "\n" not in out and "\r" not in out
    assert "\x1b" not in out and "\x00" not in out
    assert out != ""


def test_long_input_is_truncated():
    assert len(visible("A" * 5000)) <= 120


def test_full_screen_renders_without_error():
    from rich.console import Console
    state = _state_from(FIXTURE)
    console = Console(width=100, height=40, file=open(os.devnull, "w"))
    console.print(render.render(state, time.monotonic(), 40, console=console, width=100))


# ---- the fix actually holds ---------------------------------------------

def test_fix_check_confirms_the_fixture_bypass_is_closed():
    check = guards.verify_fix("path_traversal", "../public_backup/id_rsa")
    assert check.available
    assert check.broke_before, "must reproduce against the original guard"
    assert check.blocked_after, "the fix must block it"
    assert check.safe_inputs_ok, "the fix must not break normal traffic"
    assert check.holds


def test_unregistered_case_degrades_instead_of_crashing():
    check = guards.verify_fix("case_nobody_registered", "whatever")
    assert not check.available
    assert not check.holds
    assert "case_nobody_registered" in check.reason


def test_fix_check_survives_a_guard_that_raises():
    boom = guards.FixedGuard(
        case_name="boom",
        broken=lambda s: (_ for _ in ()).throw(ValueError("bad input")),
        fixed=lambda s: (_ for _ in ()).throw(ValueError("bad input")),
        safe_inputs=["ok"],
    )
    guards.FIXED_GUARDS["boom"] = boom
    try:
        check = guards.verify_fix("boom", "anything")
        assert check.available
        assert not check.holds          # a throwing guard is not a passing fix
    finally:
        del guards.FIXED_GUARDS["boom"]


def test_fixed_guard_still_allows_every_safe_input():
    for name, entry in guards.FIXED_GUARDS.items():
        for safe in entry.safe_inputs:
            assert entry.fixed(safe) is True, f"{name}: fix rejects safe input {safe!r}"


def test_every_registered_case_has_a_real_before_and_after():
    """A mirror where broken and fixed behave identically proves nothing."""
    for name, entry in guards.FIXED_GUARDS.items():
        assert entry.broken is not entry.fixed, f"{name}: no actual fix registered"


# ---- fixture integrity --------------------------------------------------

def test_fixture_is_valid_contract_shaped_jsonl():
    allowed = {"attempt", "candidate", "verdict", "done"}
    with open(FIXTURE) as fh:
        for n, line in enumerate(fh, start=1):
            event = json.loads(line)
            assert event["kind"] in allowed, f"line {n}: unknown kind"
            if event["kind"] != "done":
                assert isinstance(event["payload"], dict), f"line {n}"


def test_every_candidate_in_the_fixture_gets_a_verdict():
    events = [json.loads(l) for l in open(FIXTURE)]
    candidates = {e["payload"]["input"] for e in events if e["kind"] == "candidate"}
    verdicts = {e["payload"]["input"] for e in events if e["kind"] == "verdict"}
    assert candidates == verdicts


def test_fixture_verdicts_agree_with_the_oracle():
    """The fixture must not claim a break the guard does not actually have."""
    events = [json.loads(l) for l in open(FIXTURE)]
    for event in events:
        if event["kind"] != "verdict":
            continue
        payload = event["payload"]
        assert payload["is_real_bypass"] == make_fixture.oracle(payload["input"]), \
            f"fixture lies about {payload['input']!r}"


def test_fixture_avoids_the_banned_textbook_bypass():
    """CONTRACT.md hero-case rule: the winning input must not be a cheat-sheet entry."""
    events = [json.loads(l) for l in open(FIXTURE)]
    winner = next(e["payload"]["input"] for e in events
                  if e["kind"] == "verdict" and e["payload"]["is_real_bypass"])
    assert "%2e" not in winner.lower()
    assert "etc/passwd" not in winner


# ---- the money panel is never clipped -----------------------------------

@pytest.mark.parametrize("height", [16, 18, 20, 24, 25, 30, 40, 60])
@pytest.mark.parametrize("width", [60, 80, 100, 140])
def test_result_panel_is_never_clipped(height, width):
    """The confirmed bypass and the fix sit at the bottom of the screen.

    If the layout ever overshoots the terminal height, rich clips from the
    bottom -- silently cutting off exactly the thing the demo exists to show.
    """
    from rich.console import Console

    state = _state_from(FIXTURE)
    console = Console(width=width, height=height, file=open(os.devnull, "w"))
    layout = render.render(state, time.monotonic(), height, console=console, width=width)
    lines = console.render_lines(
        layout, console.options.update(width=width, height=height), pad=False
    )
    assert len(lines) == height, "layout must fill the screen exactly, never overflow"

    text = ["".join(seg.text for seg in line) for line in lines]
    assert any("╰" in row for row in text[-2:]), "result panel lost its bottom border"
    assert any("REAL BYPASS CONFIRMED" in row for row in text), "headline was clipped"
