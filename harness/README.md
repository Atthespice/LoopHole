# harness/ — owner: TBD (see CONTRACT.md section 0)

Owns:
- The three `GuardCase` objects agreed in CONTRACT.md section 0 — each with a
  real, self-constructed bug (no textbook cheat-sheet bypasses), a working
  `oracle`, and a list of `safe_inputs`.
- `race.py` — the Phase 0 go/no-go script (all three gates).

Must not assume anything about how the loop generates inputs.

Read CONTRACT.md in full before starting. Only import from `shared/`.
