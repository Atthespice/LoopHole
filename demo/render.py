"""Owned by: demo/ (see CONTRACT.md).

Screen state and rendering. Pure presentation: DemoState ingests log events and
render() turns that state into something rich can draw. Neither touches the
filesystem or any other folder's code, which keeps both of them testable without
a terminal.

Inputs on this screen are hostile by construction -- they are attack strings. All
of them go through visible() and are rendered as Text objects, never as rich
markup, so an input containing "[" or a newline cannot corrupt the display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.align import Align
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from guards import FixCheck, verify_fix
from tail import ATTEMPT, CANDIDATE, DONE, MALFORMED, VERDICT, Event

# The team has not settled Loophole vs. Mwanya (CONTRACT.md section 0).
# One constant, one line to change.
PRODUCT_NAME = "LoopHole"

_CONTROL_NAMES = {
    "\n": "\\n", "\r": "\\r", "\t": "\\t", "\0": "\\0", "\x1b": "\\e",
}


def visible(value: Any, limit: int = 120) -> str:
    """Render an attack string so the room can actually see what it was.

    Control characters are the whole point of some bypasses -- a trailing "\\n"
    that defeats a `$`-anchored regex is invisible on screen otherwise, which
    would make the demo look like magic instead of evidence.
    """
    text = value if isinstance(value, str) else repr(value)
    out = []
    for ch in text:
        if ch in _CONTROL_NAMES:
            out.append(_CONTROL_NAMES[ch])
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    rendered = "".join(out)
    if len(rendered) > limit:
        rendered = rendered[: limit - 1] + "…"
    return rendered or "(empty string)"


def clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    return f"{int(seconds) // 60:02d}:{seconds % 60:04.1f}"


@dataclass
class AttemptRow:
    index: int
    input: str
    allowed: bool
    reasoning: str = ""
    is_candidate: bool = False


@dataclass
class DemoState:
    """Everything on screen, derived only from the run log."""

    case_name: str = ""
    description: str = ""
    replayed: bool = False          # elapsed time is replay pacing, not a real run
    static: bool = False            # whole log read at once; elapsed time is meaningless

    attempts: list[AttemptRow] = field(default_factory=list)
    n_attempts: int = 0
    n_blocked: int = 0
    n_allowed: int = 0
    n_candidates: int = 0
    n_false_alarms: int = 0         # verdicts with is_real_bypass=False
    n_malformed: int = 0

    confirmed: dict[str, Any] | None = None
    fix_check: FixCheck | None = None

    first_event_at: float | None = None
    last_event_at: float | None = None
    broke_at: float | None = None   # when the confirmed verdict landed
    done: bool = False

    # ---- ingest ---------------------------------------------------------

    def ingest(self, event: Event) -> None:
        if self.first_event_at is None:
            self.first_event_at = event.received_at
        self.last_event_at = event.received_at

        if event.kind == MALFORMED:
            self.n_malformed += 1
            return

        name = event.payload.get("case_name")
        if name and not self.case_name:
            self.case_name = str(name)

        if event.kind == ATTEMPT:
            self._ingest_attempt(event)
        elif event.kind == CANDIDATE:
            self._ingest_candidate(event)
        elif event.kind == VERDICT:
            self._ingest_verdict(event)
        elif event.kind == DONE:
            self.done = True

    def _ingest_attempt(self, event: Event) -> None:
        allowed = bool(event.payload.get("guard_result"))
        self.n_attempts += 1
        if allowed:
            self.n_allowed += 1
        else:
            self.n_blocked += 1
        self.attempts.append(
            AttemptRow(
                index=self.n_attempts,
                input=str(event.payload.get("input", "")),
                allowed=allowed,
                reasoning=str(event.payload.get("reasoning") or ""),
            )
        )
        # Keep memory flat on a long run; only the tail is ever drawn.
        if len(self.attempts) > 400:
            del self.attempts[:200]

    def _ingest_candidate(self, event: Event) -> None:
        self.n_candidates += 1
        candidate_input = str(event.payload.get("input", ""))
        for row in reversed(self.attempts):
            if row.input == candidate_input:
                row.is_candidate = True
                break

    def _ingest_verdict(self, event: Event) -> None:
        if not bool(event.payload.get("is_real_bypass")):
            self.n_false_alarms += 1
            return
        if self.confirmed is not None:
            return  # first confirmed break is the story; ignore later ones
        self.confirmed = dict(event.payload)
        self.broke_at = event.received_at
        self.fix_check = verify_fix(
            self.case_name or str(event.payload.get("case_name", "")),
            str(event.payload.get("input", "")),
        )

    # ---- derived --------------------------------------------------------

    def elapsed(self, now: float) -> float:
        if self.first_event_at is None:
            return 0.0
        end = self.last_event_at if self.done else now
        return (end or now) - self.first_event_at

    def time_to_break(self) -> float | None:
        if self.broke_at is None or self.first_event_at is None:
            return None
        return self.broke_at - self.first_event_at


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_OK = "bold green"
_BAD = "bold red"
_DIM = "grey50"


def _header(state: DemoState, now: float) -> RenderableType:
    title = Text(f" {PRODUCT_NAME} ", style="bold white on blue")
    title.append("  ")
    title.append(state.case_name or "waiting for run log…", style="bold cyan")

    stats = Table.grid(padding=(0, 3))
    stats.add_column()
    stats.add_column()
    stats.add_column()
    stats.add_column()
    stats.add_column(justify="right")

    if state.static:
        elapsed = Text("completed run", style=_DIM)
    else:
        elapsed = Text(clock(state.elapsed(now)), style="bold")
        if state.replayed:
            elapsed.append("  (replay)", style=_DIM)

    stats.add_row(
        Text.assemble(("attempts ", _DIM), (str(state.n_attempts), "bold")),
        Text.assemble(("blocked ", _DIM), (str(state.n_blocked), "bold")),
        Text.assemble(
            ("got through ", _DIM),
            (str(state.n_allowed), _BAD if state.n_allowed else "bold"),
        ),
        Text.assemble(
            ("candidates ", _DIM),
            (str(state.n_candidates), "bold yellow" if state.n_candidates else "bold"),
        ),
        elapsed,
    )

    extra = []
    if state.n_false_alarms:
        extra.append(Text(f"false alarms ruled out: {state.n_false_alarms}", style=_DIM))
    if state.n_malformed:
        extra.append(Text(f"unreadable log lines: {state.n_malformed}", style="yellow"))

    return Panel(Group(title, stats, *extra), border_style="blue", padding=(0, 1))


def _feed(state: DemoState, rows: int) -> RenderableType:
    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(justify="right", width=5, style=_DIM)
    table.add_column(ratio=1, overflow="fold")
    table.add_column(justify="right", width=14)

    visible_rows = state.attempts[-max(1, rows):]
    if not visible_rows:
        table.add_row("", Text("waiting for the loop to start attacking…", style=_DIM), "")

    for row in visible_rows:
        is_winner = (
            state.confirmed is not None
            and row.input == str(state.confirmed.get("input", ""))
        )
        if is_winner:
            marker = Text("► ALLOWED ◄", style="bold white on red")
            body = Text(visible(row.input), style="bold white on red")
        elif row.allowed:
            marker = Text("ALLOWED", style="bold yellow")
            body = Text(visible(row.input), style="bold yellow")
        else:
            marker = Text("blocked", style=_DIM)
            body = Text(visible(row.input), style="white")
        table.add_row(str(row.index), body, marker)

    return Panel(
        table,
        title=Text("attacking the guard", style=_DIM),
        title_align="left",
        border_style="grey35",
        padding=(0, 1),
    )


def _fix_lines(check: FixCheck | None) -> list[RenderableType]:
    if check is None:
        return []
    if not check.available:
        return [
            Text.assemble(
                ("after fix:  ", _DIM),
                ("not verified here — ", "yellow"),
                (check.reason, _DIM),
            ),
            Text(
                "  (register this case in demo/guards.py to re-run it live)",
                style=_DIM,
            ),
        ]

    before = Text.assemble(
        ("before fix: ", _DIM),
        ("GOT THROUGH" if check.broke_before else "did not reproduce",
         _BAD if check.broke_before else "yellow"),
    )
    after = Text.assemble(
        ("after fix:  ", _DIM),
        ("BLOCKED" if check.blocked_after else "STILL GETS THROUGH",
         _OK if check.blocked_after else _BAD),
    )
    ok = check.safe_inputs_ok
    safe = Text.assemble(
        ("normal traffic: ", _DIM),
        (
            f"all {len(check.safe_results)} safe inputs still allowed" if ok
            else "THE FIX BROKE NORMAL TRAFFIC",
            _OK if ok else _BAD,
        ),
    )
    return [before, after, safe]


def _result(state: DemoState) -> RenderableType:
    if state.confirmed is None:
        if state.done:
            return Panel(
                Align.center(
                    Text("run finished with no confirmed bypass", style="bold yellow")
                ),
                border_style="yellow",
                padding=(1, 1),
            )
        hint = Text("no bypass yet — the guard is holding so far", style=_DIM)
        if state.n_candidates:
            hint = Text("candidate found, waiting on the verdict…", style="bold yellow")
        return Panel(Align.center(hint), border_style="grey35", padding=(0, 1))

    verdict = state.confirmed
    banner = Text("██  REAL BYPASS CONFIRMED  ██", style="bold white on red")
    took = state.time_to_break()
    if took is not None and not state.static:
        banner.append(f"   broke in {clock(took)}", style="bold red")
    banner.append(f"   after {state.n_attempts} attempts", style="bold red")

    # A grid keeps wrapped explanation lines aligned under their label instead
    # of running back to the left margin.
    details = Table.grid(padding=(0, 1))
    details.add_column(justify="right", width=7, style=_DIM)
    details.add_column(ratio=1, overflow="fold")
    details.add_row("input:", Text(visible(verdict.get("input", "")), style=_BAD))
    details.add_row(
        "why:", Text(str(verdict.get("explanation", "")) or "—", style="white")
    )
    details.add_row(
        "FIX:", Text(str(verdict.get("suggested_fix", "")) or "—", style=_OK)
    )

    body: list[RenderableType] = [
        Align.center(banner),
        Text(""),
        details,
        Text(""),
        *_fix_lines(state.fix_check),
    ]

    holds = state.fix_check is not None and state.fix_check.holds
    return Panel(
        Group(*body),
        title=Text(
            " the hole, and the one line that closes it ",
            style="bold white on red",
        ),
        border_style=_OK if holds else "red",
        padding=(0, 2),
    )


def render(
    state: DemoState,
    now: float,
    height: int = 40,
    console: Console | None = None,
    width: int | None = None,
) -> RenderableType:
    """Build the full screen.

    The result panel is measured, not guessed. It carries the one thing the whole
    demo exists to show, so it gets the height it needs and the attempt feed
    absorbs the difference -- never the other way round.
    """
    header = _header(state, now)
    result = _result(state)

    header_h = _measured(header, console, width, fallback=5)
    result_h = _measured(result, console, width, fallback=14)

    sections: list[Layout] = [Layout(header, name="header", size=header_h)]
    available = max(1, height - header_h)

    # The sizes below must sum to exactly `height`. If they overshoot, rich
    # clips the bottom of the screen -- which is where the confirmed bypass and
    # the fix live. So when the terminal is too short for both panels, the feed
    # is dropped entirely and the result panel keeps the room.
    if result_h >= available - 2:
        sections.append(Layout(result, name="result", size=available))
    else:
        feed_h = available - result_h
        sections.append(Layout(_feed(state, feed_h - 2), name="feed", size=feed_h))
        sections.append(Layout(result, name="result", size=result_h))

    layout = Layout()
    layout.split_column(*sections)
    return layout


def _measured(
    renderable: RenderableType,
    console: Console | None,
    width: int | None,
    fallback: int,
) -> int:
    """Exact rendered height of a panel, so nothing important gets clipped."""
    if console is None:
        return fallback
    try:
        options = console.options.update(
            width=width or console.size.width, height=None
        )
        return len(console.render_lines(renderable, options, pad=False))
    except Exception:
        return fallback
