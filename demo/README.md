# demo/ — owner: knelso (Nelson)

Owns the live on-screen demo: the part the room actually watches.

Per CONTRACT.md, this folder **only ever reads the run log**. It never imports
`loop/`, `verdict/`, or `harness/`. That isolation is the point — everything here
already works end to end against a fixture log, before the other three folders
exist.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# one terminal, full rehearsal — writes a fake run log and watches it live
.venv/bin/python demo/replay.py --watch

# what happens on the night: watch a real run as loop/ and verdict/ write it
.venv/bin/python demo/main.py runs/path_traversal.jsonl

# static render of a finished log, for screenshots
.venv/bin/python demo/main.py demo/fixtures/path_traversal.jsonl --no-follow

.venv/bin/python -m pytest demo/ -q
```

`replay.py --speed 8` speeds up rehearsal. Drop the flag for stage pacing.

## Files

| file | what it does |
|---|---|
| `main.py` | `watch(log_path) -> None` — the contract entry point, plus a CLI |
| `tail.py` | reads the JSONL run log; survives missing files, half-written lines, garbage |
| `render.py` | `DemoState` (log → screen state) and `render()` (state → rich layout) |
| `guards.py` | local before/after guard mirrors, used only to prove the fix holds |
| `make_fixture.py` | regenerates the fixture log from the real guard + an oracle |
| `replay.py` | plays a fixture into `runs/` the way `loop/` and `verdict/` will |
| `fixtures/` | contract-shaped sample run logs |
| `test_demo.py` | 66 tests |

## What's on screen

Header with live counters and an elapsed clock; a scrolling feed of every attempt
marked `blocked` / `ALLOWED`; and a result panel that takes over the moment a
`verdict` with `is_real_bypass=true` lands — showing the input, the plain-English
reason, the one-line fix, and then the fix **re-run live**: bypass now blocked,
every safe input still allowed.

## Three things the team should know

**1. `guards.py` exists because the contract asks for something the log can't give.**
CONTRACT.md says demo/ must "re-run the guard with the fix applied to show it
holds", but `suggested_fix` is a one-line *string* and demo/ may not import other
folders. So demo/ keeps its own mirror of each guard's broken and fixed form,
used *only* for the closing panel. **It is a mirror, not the source of truth —
`harness/` owns the real guards, and if one changes there, `demo/guards.py` must
be re-synced by hand.** Unregistered cases degrade gracefully: the demo still
shows the bypass and the fix, it just prints "not verified here" instead of the
live re-run. If we'd rather kill the drift risk, the alternative is adding an
executable `fixed_guard_source` to the `Verdict` shape — that's a shared-contract
change and needs the whole team.

**2. The wire format carries no timestamps.** The "much faster than the old tools"
claim is a timing claim, but `Attempt` has no time field. The demo therefore
stamps events *as it receives them*, which is honest for a live tail — it's how
long the room actually waited. Replayed fixtures are labelled `(replay)` and a
`--no-follow` render shows "completed run" instead of a fake stopwatch. If we want
real per-attempt timings in the final cut, `loop/` needs to add a timestamp and
that's a contract change.

**3. The fixture's hero case is a stand-in, not the team's choice.** CONTRACT.md
section 0 is still blank, so `harness/` hasn't picked the three real cases. The
fixture uses a self-constructed prefix-anchoring bug: the guard resolves the path
correctly, then checks `startswith("/srv/app/public")` with **no trailing
separator** — so `../public_backup/id_rsa` lands in a sibling directory outside
the safe root and still satisfies the check. It deliberately obeys the hero-case
rule: `%2e%2e` and `../../../etc/passwd` appear only as attempts that *fail*, and
a test enforces that the winning input is neither. Swap in the real cases when
harness/ lands — nothing in the demo is tied to this one.

The fixture also contains two **false alarms** — inputs that get past the guard
but never actually escape — so the demo shows `verdict/` doing real work instead
of rubber-stamping the first thing that slips through. That's a better story for
the judges than a clean first-try win.

## Contract compliance

- Entry point is `watch(log_path) -> None`. Extra arguments are keyword-only with
  defaults, so a bare `watch(path)` works as specified.
- No imports from `loop/`, `verdict/`, or `harness/`. The run log is the only input.
- Reads the four contract event kinds (`attempt`, `candidate`, `verdict`, `done`)
  and ignores anything else rather than crashing.
