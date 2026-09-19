# verdict/ — owner: Thiararapeter (see CONTRACT.md section 0)

Owns: the real-break judge.

- Input: a `GuardCase` and a `Candidate` (tail `runs/<case_name>.jsonl` for
  `candidate` events, or call `judge()` directly for local testing).
- Output: appends a `verdict` event with `suggested_fix` filled in.
- Entry point: `judge(case, candidate) -> Verdict`

Must not assume anything about how the loop found the candidate.
Must not import from loop/ or demo/. Only import from `shared/`.

Read CONTRACT.md in full before starting.

## Usage

```python
from verdict.judge import judge, tail_and_judge

v = judge(case, candidate)                       # pure, deterministic, no I/O
tail_and_judge(case, "runs/<case_name>.jsonl")   # follows the log, appends verdict events, stops on "done"
```

Live run against a harness case (the only place verdict/ touches another
folder, since a `GuardCase` holds callables and can't arrive over JSONL):

```
python -m verdict.judge <case_name> [runs/<case_name>.jsonl]
```

## How a ruling is made

A candidate is a real bypass only if all three hold:

1. Re-running `case.guard` lets the input through (the loop is not trusted).
2. `case.oracle` confirms the input reaches the protected resource.
3. The input is not in `case.safe_inputs`.

Guard or oracle crashes are ruled *not* a bypass and named in the explanation,
never swallowed. A restarted judge skips candidates that already have a verdict.

`suggested_fix` is a one-line heuristic keyed on the shape of the input
(NUL bytes, double-encoding, NFKC collisions, backslashes, SQL metacharacters,
host tricks, ...), falling back to the case name/description.

Tests: `pytest verdict/`
