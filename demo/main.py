"""Owned by: demo/ (see CONTRACT.md).

Tails runs/<case_name>.jsonl and renders attempts live with rich. Never imports
loop/ or verdict/ directly -- read the log file only.

Entry point, per the contract:

    watch(log_path) -> None

Usage:
    python demo/main.py runs/path_traversal.jsonl        # follow a live run
    python demo/main.py demo/fixtures/path_traversal.jsonl --replay
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

# Run as a script from anywhere in the repo without needing the package on PATH.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live

from render import PRODUCT_NAME, DemoState, clock, render
from tail import Event, read_all, tail_events


class _Screen:
    """Renderable wrapper so rich's refresh timer redraws the clock between events.

    The tailer spends most of its life asleep waiting on the log. If the screen
    only redrew when an event arrived, the elapsed timer would freeze -- and the
    timer is the point of the whole pitch.
    """

    def __init__(self, state: DemoState) -> None:
        self.state = state
        self.lock = threading.Lock()

    def ingest(self, event: Event) -> None:
        with self.lock:
            self.state.ingest(event)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        with self.lock:
            height = options.height or console.size.height
            yield render(
                self.state,
                time.monotonic(),
                height,
                console=console,
                width=options.max_width,
            )


def watch(
    log_path: str,
    *,
    follow: bool = True,
    replayed: bool = False,
    timeout: float | None = None,
    console: Console | None = None,
) -> None:
    """Render a run log on screen, live.

    The extra keyword arguments all default, so the contract's `watch(log_path)`
    call works unchanged.
    """
    console = console or Console()
    state = DemoState(replayed=replayed)
    screen = _Screen(state)

    if not follow:
        state.static = True
        for event in read_all(log_path):
            screen.ingest(event)
        console.print(screen)
        _print_summary(console, state)
        return

    with Live(screen, console=console, refresh_per_second=12, screen=False) as live:
        try:
            for event in tail_events(log_path, timeout=timeout):
                screen.ingest(event)
        except KeyboardInterrupt:
            pass
        live.refresh()

    _print_summary(console, state)


def _print_summary(console: Console, state: DemoState) -> None:
    """One plain line after the live screen, so the result survives in scrollback."""
    console.print()  # Live's last frame ends without a newline
    if state.confirmed is not None:
        took = state.time_to_break()
        when = f" in {clock(took)}" if (took is not None and not state.static) else ""
        console.print(
            f"[bold red]{PRODUCT_NAME}[/]: broke [bold]{state.case_name}[/]{when} "
            f"after {state.n_attempts} attempts.",
            highlight=False,
        )
        check = state.fix_check
        if check is not None and check.available:
            if check.holds:
                console.print(
                    "[bold green]The fix holds[/]: the bypass is blocked and every "
                    "safe input still gets through.",
                    highlight=False,
                )
            else:
                console.print(
                    "[bold yellow]The fix did NOT fully hold[/] — see the panel above.",
                    highlight=False,
                )
    elif state.done:
        console.print(
            f"[bold yellow]{PRODUCT_NAME}[/]: run finished, no confirmed bypass "
            f"after {state.n_attempts} attempts.",
            highlight=False,
        )
    else:
        console.print(f"[{'grey50'}]{PRODUCT_NAME}: stopped before the run finished.[/]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo",
        description=f"{PRODUCT_NAME} live demo — tails a run log and shows the break.",
    )
    parser.add_argument("log_path", help="path to runs/<case_name>.jsonl")
    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="render the log once and exit instead of tailing it",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="label the timer as replay pacing rather than a real run",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="give up after N seconds with no 'done' event",
    )
    args = parser.parse_args(argv)

    watch(
        args.log_path,
        follow=not args.no_follow,
        replayed=args.replay,
        timeout=args.timeout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
