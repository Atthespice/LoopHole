# LoopHole — team contract

Read this whole file together before anyone splits off. The contract section below is
the one thing nobody changes solo — if it needs to change once you're building, stop
and agree on the change as a group first, then everyone re-pulls it.

## 0. Decide together, right now

Fill these in before forking into folders. Don't skip this — it's what keeps four
people from building four different things.

- **Name:** Loophole, or Mwanya (Swahili for "gap/opening" — may land better with
  local judges)? → `___________`
- **The three guard functions to attack:** (path traversal check, DB input cleaner,
  and allowlist check are the suggested defaults)
  1. `___________`
  2. `___________`
  3. `___________`
- **Who owns which folder:**
  - Harness & go/no-go → `___________`
  - Attack loop → `___________`
  - Verdict (real-break judge) → `___________`
  - Demo → `___________`
- **Stop rule:** if the go/no-go race (Phase 0 below) doesn't clearly beat a plain
  fuzzer on speed and false-positive rate, we stop and pick a different idea — no
  arguments later. Agreed? → `yes / no`

## Tech stack

Python 3.11+, one language across every folder so nobody is blocked on someone
else's build step.

- `anthropic` — SDK for both the attacking model and the previous-model baseline
  (see Gate 1 below). Needs `ANTHROPIC_API_KEY` in the environment, never committed.
- `hypothesis` — the classic-fuzzer baseline (Gate 2 below).
- `rich` — live-updating terminal demo. No web server to build in one night.
- `pytest` — tests for guard functions and oracles.
- JSONL files (see the wire format below) — the only thing that crosses folder
  boundaries at runtime.

## Phase 0 — go/no-go, before anyone forks off (do this together, ~1 hour)

Three gates. All three must pass before anyone opens a folder and starts building
their piece. This can be one throwaway script — it doesn't need to follow the
contract below yet.

**Gate 1 — beat the actual opponent.** The bake-off is model vs. model in the
*same* loop, not new-model-with-a-loop vs. old-tools-with-no-loop. Run the
identical generate → run → observe → mutate loop with the previous Claude model
and with the current one, same guard case, same budget. If the previous model
also finds the bypass, the Breakthrough-track claim doesn't hold — the loop found
it, not the newer model, and you need a harder case or a different claim.

**Gate 2 — beat a classic fuzzer too.** Same guard case, race the loop against
`hypothesis`. This is the secondary claim ("the loop itself is worth building"),
not the primary one — don't let a win here substitute for Gate 1.

**Gate 3 — check the model actually cooperates.** Before writing any loop code,
send one prompt asking the model to produce a bypass input for a guard function,
framed clearly as authorized security testing on your own code (not a raw "hack
this" prompt). Confirm you get a real candidate back, not a refusal or a hedge.
Claude models carry real reinforcement around dual-use cyber content — find out
in the first hour whether your framing gets a straight answer, not at hour eight
when the loop is built and quietly returning nothing useful.

**Hero-case rule, applies to whichever case you use for gates and the final demo:**
the bug must be one the team constructed, not a textbook cheat-sheet entry.
`%2e%2e%2f` / `../../../etc/passwd` is disqualified — every model already knows
it, so beating it proves nothing. Use something that needs actual reasoning about
your specific guard's logic (a normalization edge case, an encoding collision,
an anchoring bug in a regex you wrote yourselves).

Only move to Phase 1 once all three gates pass on a self-constructed case.

## Phase 1 — fork into folders

```
LoopHole/
  CONTRACT.md      <- this file, the one everyone agreed on
  shared/
    types.py        <- copy the code block below verbatim, do not edit alone
  harness/          <- Person A
  loop/             <- Person B
  verdict/          <- Person C
  demo/             <- Person D
```

Each person works only inside their own folder plus `shared/types.py` (read-only
once copied). Nobody needs to read anyone else's code to build their piece — that's
what the shapes below are for.

## The shared contract

Copy this into `shared/types.py` before anyone starts. This is the one file
everyone has to agree on first — every folder imports from it, nobody edits it
alone once copied.

```python
# shared/types.py — do not edit without full team agreement.

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class GuardCase:
    """One vulnerable guard function to attack. Owned by harness/."""
    name: str                      # e.g. "path_traversal"
    description: str               # one line, plain English
    guard: Callable[[str], bool]   # True = input allowed through, False = blocked
    oracle: Callable[[str], bool]  # ground truth: True = input actually reaches
                                    # the protected resource (used to confirm a
                                    # break is real, not a false alarm)
    safe_inputs: list[str]         # known-good inputs; must never be flagged


@dataclass
class Attempt:
    """One try the loop made against a GuardCase. Owned by loop/."""
    case_name: str
    input: str
    guard_result: bool             # what the guard said: True = let it through
    reasoning: Optional[str] = None


@dataclass
class Candidate:
    """An attempt that got past the guard, not yet confirmed real. Owned by loop/."""
    case_name: str
    input: str
    attempt_index: int


@dataclass
class Verdict:
    """The ruling on a Candidate. Owned by verdict/."""
    case_name: str
    input: str
    is_real_bypass: bool           # oracle-confirmed
    explanation: str               # plain English, shown live in the demo
    suggested_fix: str             # one line
```

### The wire format (how the folders talk without importing each other)

`loop/` and `verdict/` never call into each other's code directly. They communicate
by appending JSON lines to a shared run log, one file per guard case:

```
runs/<case_name>.jsonl
```

Each line is one event:

```json
{"kind": "attempt", "payload": {...Attempt...}}
{"kind": "candidate", "payload": {...Candidate...}}
{"kind": "verdict", "payload": {...Verdict...}}
{"kind": "done"}
```

`demo/` only ever reads this file (tail it live). This means `demo/` can be built
and tested against a fake `.jsonl` file before `loop/` or `verdict/` exist at all —
and `loop/`/`verdict/` can be built and tested with fixture `GuardCase`s before
`harness/` is finished.

## Folder contracts — what each person owns and must deliver

### `harness/` — test cases + go/no-go
- Deliver: the three `GuardCase` objects (agreed in section 0), each with a real
  bug, a working `oracle`, and a list of `safe_inputs`.
- Deliver: the Phase 0 race script (can be the same one from the go/no-go step,
  cleaned up).
- Must not: assume anything about how the loop generates inputs.

### `loop/` — the attacking loop
- Input: a single `GuardCase`, a time/attempt budget.
- Output: appends `attempt` and `candidate` events to `runs/<case_name>.jsonl` as
  it goes.
- Entry point: `run_loop(case: GuardCase, budget: int, log_path: str) -> None`
- Must not: decide whether a candidate is a *real* break — that's verdict's job.

### `verdict/` — real-break judge
- Input: tails `runs/<case_name>.jsonl` for `candidate` events (or is called
  directly with a `Candidate` + its `GuardCase`, for local testing).
- Output: appends a `verdict` event per candidate, with `suggested_fix` filled in.
- Entry point: `judge(case: GuardCase, candidate: Candidate) -> Verdict`
- Must not: assume anything about how the loop found the candidate.

### `demo/` — on-screen demo
- Input: tails `runs/<case_name>.jsonl`, renders attempts live, highlights the
  moment a `verdict` with `is_real_bypass=True` lands, shows the fix, then re-runs
  the guard with the fix applied to show it holds.
- Must not: call `loop/` or `verdict/` code directly — read the log file only, so
  this folder can be built and demoed against a fake log before the others exist.

## How to use this file

1. Fill in section 0 together, as a team, before anyone opens a laptop separately.
2. Everyone copies the `shared/types.py` code block verbatim into their own clone.
3. Each person opens Claude Code **inside their own folder** (`cd harness/`,
   `cd loop/`, etc.) and pastes only their folder's contract section above, plus
   this file for reference. That's the entire brief needed to build in isolation.
4. If a shape in `shared/types.py` turns out to be wrong mid-build, stop, raise it
   with the group, agree on the fix, and have everyone re-copy it — don't patch it
   solo, that's what causes the collisions this file exists to prevent.
