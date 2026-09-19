"""Owned by: demo/ (see CONTRACT.md).

Plays a fixture log into runs/<case_name>.jsonl one event at a time, the way
loop/ and verdict/ will write it for real. This is a stand-in for those folders,
not a substitute: it only ever appends contract-shaped lines to a file, exactly
the surface demo/ is allowed to see.

Two ways to use it:

    # one command, one terminal -- what you want on stage
    python demo/replay.py --watch

    # two terminals, closer to the real thing
    python demo/replay.py                       # terminal 1: writes the log
    python demo/main.py runs/path_traversal.jsonl   # terminal 2: watches it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import watch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# How long to hold on each kind of event, in seconds. The pause before a verdict
# is deliberate: it is the beat where the room leans in.
PACING = {
    "attempt": 0.45,
    "candidate": 0.30,
    "verdict": 1.30,
    "done": 0.60,
}
CONFIRMED_PAUSE = 1.0   # extra beat just before the real bypass lands


def replay(fixture: str, target: str, speed: float = 1.0) -> None:
    """Append fixture's events to target with demo pacing. Truncates target first."""
    with open(fixture, "r", encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip()]

    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    # Start clean: a stale log from the last rehearsal would show up as history.
    with open(target, "w", encoding="utf-8"):
        pass

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"kind": "attempt"}

        payload = event.get("payload") or {}
        if event.get("kind") == "verdict" and payload.get("is_real_bypass"):
            time.sleep(CONFIRMED_PAUSE / max(speed, 0.01))

        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line if line.endswith("\n") else line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

        time.sleep(PACING.get(str(event.get("kind")), 0.3) / max(speed, 0.01))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replay",
        description="Play a fixture run log into runs/ the way loop/ and verdict/ will.",
    )
    parser.add_argument(
        "--fixture",
        default=os.path.join(HERE, "fixtures", "path_traversal.jsonl"),
        help="fixture log to play (default: demo/fixtures/path_traversal.jsonl)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="where to write (default: runs/<fixture name>.jsonl)",
    )
    parser.add_argument(
        "--speed", type=float, default=1.0, help="playback speed multiplier"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="also run the demo screen in this terminal",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.fixture):
        print(
            f"fixture not found: {args.fixture}\n"
            f"run `python demo/make_fixture.py` first",
            file=sys.stderr,
        )
        return 1

    target = args.target or os.path.join(
        REPO, "runs", os.path.basename(args.fixture)
    )

    if not args.watch:
        print(f"replaying {os.path.basename(args.fixture)} -> {target}")
        print(f"now run:  python demo/main.py {target}")
        replay(args.fixture, target, args.speed)
        print("replay finished")
        return 0

    writer = threading.Thread(
        target=replay, args=(args.fixture, target, args.speed), daemon=True
    )
    writer.start()
    # The tailer waits for the file, so there is no race with the writer here.
    watch(target, replayed=True, timeout=180)
    writer.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
