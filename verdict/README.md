# verdict/ — owner: TBD (see CONTRACT.md section 0)

Owns: the real-break judge.

- Input: a `GuardCase` and a `Candidate` (tail `runs/<case_name>.jsonl` for
  `candidate` events, or call `judge()` directly for local testing).
- Output: appends a `verdict` event with `suggested_fix` filled in.
- Entry point: `judge(case, candidate) -> Verdict`

Must not assume anything about how the loop found the candidate.
Must not import from loop/ or demo/. Only import from `shared/`.

Read CONTRACT.md in full before starting.
