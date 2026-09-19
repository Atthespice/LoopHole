# demo/ — owner: TBD (see CONTRACT.md section 0)

Owns: the live on-screen demo.

- Input: tails `runs/<case_name>.jsonl`, renders attempts live, highlights the
  moment a `verdict` with `is_real_bypass=True` lands, shows the fix, then
  re-runs the guard with the fix applied to show it holds.
- Entry point: `watch(log_path) -> None`

Must not call loop/ or verdict/ code directly — read the log file only. This
means demo/ can be built and shown working against a fake `.jsonl` file before
loop/ or verdict/ exist.

Read CONTRACT.md in full before starting.
