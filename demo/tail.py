"""Owned by: demo/ (see CONTRACT.md).

Reads the shared run log. This is the ONLY channel demo/ has to the rest of the
system -- no imports from loop/ or verdict/, by contract.

Wire format (CONTRACT.md), one JSON object per line, appended as the run goes:

    {"kind": "attempt",   "payload": {...Attempt...}}
    {"kind": "candidate", "payload": {...Candidate...}}
    {"kind": "verdict",   "payload": {...Verdict...}}
    {"kind": "done"}

The log is written by another process while we read it, so this tailer is built
for the messy middle: the file may not exist yet when the demo starts, the last
line may be half-written when we reach it, and a line may be malformed. None of
those are allowed to take the screen down mid-demo.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

# Event kinds defined by the contract.
ATTEMPT = "attempt"
CANDIDATE = "candidate"
VERDICT = "verdict"
DONE = "done"

# Locally generated, never written by loop/ or verdict/.
MALFORMED = "_malformed"


@dataclass
class Event:
    """One line off the run log, stamped with when WE saw it.

    The wire format carries no timestamps, so elapsed time on screen is measured
    from the demo's own clock. For a live tail that is the honest number: it is
    how long the room actually waited. For a replayed fixture it reflects the
    replay's pacing, not a real run -- which is why replayed runs are labelled.
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: float = 0.0        # time.monotonic() when this line was read
    raw: str = ""                   # original line, kept for malformed events


def parse_line(line: str, received_at: float | None = None) -> Event | None:
    """Parse one log line. Returns None for blank lines, never raises."""
    stamp = time.monotonic() if received_at is None else received_at
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return Event(kind=MALFORMED, received_at=stamp, raw=stripped)
    if not isinstance(obj, dict) or "kind" not in obj:
        return Event(kind=MALFORMED, received_at=stamp, raw=stripped)

    payload = obj.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    return Event(kind=str(obj["kind"]), payload=payload, received_at=stamp, raw=stripped)


def read_all(log_path: str) -> list[Event]:
    """Read a complete log in one shot. Used by tests and by --no-follow."""
    if not os.path.exists(log_path):
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        events = (parse_line(line) for line in fh)
        return [e for e in events if e is not None]


def tail_events(
    log_path: str,
    poll_interval: float = 0.08,
    wait_for_file: bool = True,
    stop_on_done: bool = True,
    timeout: float | None = None,
) -> Iterator[Event]:
    """Yield events from log_path as they are appended.

    Starts from the beginning of the file, so a demo can be started after the
    run has already begun and still show the full story.

    wait_for_file: block (yielding nothing) until the log appears. The loop may
        not have created it yet when the demo starts -- that is normal.
    stop_on_done: return after the contract's {"kind": "done"} event.
    timeout: give up after this many seconds with no completion. None = forever.
    """
    started = time.monotonic()
    handle = None
    buffer = ""
    inode = None

    try:
        while True:
            if timeout is not None and time.monotonic() - started > timeout:
                return

            if handle is None:
                if not os.path.exists(log_path):
                    if not wait_for_file:
                        return
                    time.sleep(poll_interval)
                    continue
                handle = open(log_path, "r", encoding="utf-8", errors="replace")
                inode = os.fstat(handle.fileno()).st_ino

            chunk = handle.read()
            if chunk:
                buffer += chunk
                # Only complete lines are safe to parse; a trailing fragment is
                # a half-written append and stays in the buffer until finished.
                *lines, buffer = buffer.split("\n")
                for line in lines:
                    event = parse_line(line)
                    if event is None:
                        continue
                    yield event
                    if stop_on_done and event.kind == DONE:
                        return
                continue

            # No new data. Check the file was not replaced or truncated under us
            # (a re-run of the same case rewrites runs/<case_name>.jsonl).
            try:
                stat = os.stat(log_path)
            except FileNotFoundError:
                handle.close()
                handle, buffer, inode = None, "", None
                time.sleep(poll_interval)
                continue

            if stat.st_ino != inode or stat.st_size < handle.tell():
                handle.close()
                handle, buffer, inode = None, "", None
                continue

            time.sleep(poll_interval)
    finally:
        if handle is not None:
            handle.close()
