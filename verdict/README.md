# verdict/ — owner: Thiararapeter (see CONTRACT.md section 0)

Owns: the real-break judge.

- Input: a `GuardCase` and a `Candidate` (tail `runs/<case_name>.jsonl` for
  `candidate` events, or call `judge()` directly for local testing).
- Output: appends a `verdict` event with `suggested_fix` filled in.
- Entry point: `judge(case, candidate) -> Verdict`

Must not assume anything about how the loop found the candidate.
Must not import from loop/, demo/, or harness/. Only import from `shared/`.

Read CONTRACT.md in full before starting.

## Usage

```python
from verdict.judge import judge, tail_and_judge

v = judge(case, candidate)                             # pure, deterministic, no I/O
res = tail_and_judge(case, "runs/<case_name>.jsonl")   # follows the log, appends verdict events
res.verdicts, res.errors
```

Live run. The `GuardCase` holds callables, so it cannot arrive over JSONL; the
caller tells the CLI where to load it from. verdict/ has no knowledge of which
module that is:

```
python -m verdict.judge <case_name> --cases harness.cases:CASES [--log runs/<case_name>.jsonl]
```

## How a ruling is made

A candidate is a real bypass only if all three hold:

1. Re-running `case.guard` lets the input through (the loop is not trusted).
2. `case.oracle` confirms the input reaches the protected resource.
3. The input is not in `case.safe_inputs`.

Guard or oracle crashes are ruled *not* a bypass and named in the explanation,
never swallowed.

`suggested_fix` is a one-line heuristic keyed on the shape of the input
(NUL bytes, double-encoding, NFKC collisions, backslashes, SQL metacharacters,
host tricks, ...), falling back to the case name/description.

## Wire-format guarantees

- **One verdict per candidate event.** The same input from two attempts gets
  two verdicts. Verdicts are appended in candidate order.
- **Restart is idempotent without collapsing attempts.** On start the judge
  counts existing verdicts per input and skips exactly that many candidate
  events for that input, then rules on the rest.
- **Nothing is silently dropped.** A line that is not valid JSON, or a
  candidate with a malformed payload, is reported via `on_error` (stderr by
  default) and returned in `TailResult.errors` with its line number. A malformed
  candidate that still carries a string `input` gets a not-a-bypass verdict so
  no candidate is left without a ruling on the wire.

## Completion protocol

`loop/` writes `done` when it has finished *generating*. The judge's verdicts
for the final candidates are appended *after* that line, so the file ends
`..., candidate, done, verdict, verdict`. The tailer returns only once it has
seen `done` and ruled on every candidate before it, so on return
`#verdicts == #candidates`.

Consumers (demo/) must therefore not treat `done` as "no more writes". Keep
tailing until the verdict count matches the candidate count. If the team
prefers a terminal marker written by verdict/ instead, that is a CONTRACT.md
change and needs group agreement; it is a two-line change here.

Tests: `pytest verdict/`
