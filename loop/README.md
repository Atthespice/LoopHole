# loop/ — owner: TBD (see CONTRACT.md section 0)

Owns: the attacking loop.

- Input: a single `GuardCase`, a time/attempt budget.
- Output: appends `attempt` and `candidate` events to `runs/<case_name>.jsonl`.
- Entry point: `run_loop(case, budget, log_path) -> None`

Must not decide whether a candidate is a *real* break — that's verdict/'s job.
Must not import from verdict/ or demo/. Only import from `shared/`.

Read CONTRACT.md in full before starting.
