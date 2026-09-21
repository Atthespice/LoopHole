# LoopHole — progress snapshot (2026-09-21)

Status: feature-complete for the pitch. All four folders are built, wired
together only through `runs/<case>.jsonl`, 129 tests pass offline, working
tree is clean on `main` (up to date with `origin/main`).

## What's built

- **harness/** — three guard cases in `harness/cases.py`, each with a
  self-constructed flaw (not a textbook cheat-sheet bug) and a ground-truth
  oracle:
  - `path_guard` — prefix check without a trailing separator, so a sibling
    dir like `safe_secrets` also satisfies `startswith(BASE_DIR)`.
  - `sql_cleaner` — blocklists `'`, `;`, and the literal string `" or "`
    (ASCII space on each side only) — misses tab/newline/SQL-comment
    whitespace variants.
  - `allowlist` — redirect/upload host allowlist with a self-built matching
    flaw (see `harness/cases.py` for the third case).
  - `harness/check.py` — keyless, deterministic regression gate against
    `harness/known_bypasses.json`; wired into `.github/workflows/ci.yml` and
    `hooks/pre-commit`.
  - `harness/fable_check.py` — live check that asks Fable 5.1 to attack a
    case first, to demonstrate its refusal on stage (`--show-refusal`).
  - `harness/race.py` — the Phase 0 go/no-go bake-off script (model vs.
    model, vs. `hypothesis` fuzzer).
- **loop/** — `run_loop(case, budget, log_path)` in `run_loop.py`; drives the
  attacking model (Sonnet 5 — see model decision below) through
  generate → run → observe → mutate, appending `attempt`/`candidate` events.
- **verdict/** — `judge(case, candidate)` / `tail_and_judge(case, log_path)`
  in `judge.py`, written by Fable 5.1 (see `Co-Authored-By` in git history).
  Confirms real bypasses against the oracle, is restart-safe (counts existing
  verdicts per input, resumes exactly once each), and keeps judging after the
  loop has already finished writing (no dropped candidates).
- **demo/** — terminal live view (`demo/main.py`) tailing the run log;
  `demo/make_fixture.py` + `demo/fixtures/` let it replay without any API
  calls or key.
- **web/** — browser mirror of the same log (`web/server.py`, `index.html`),
  served by `run.py` after a run finishes.
- **run.py** — single entry point: `--fixture` (no key), `<case>` (live
  attack + judge + serve), `--budget`, `--no-web`, `--show-refusal`, and
  auto-picks a free port if 8000 is busy.

## Key decisions already made and recorded

- **Name:** Loophole, decided 2026-09-19 (`CONTRACT.md`).
- **Attacker model:** switched from Fable 5.1 to Sonnet 5 after Fable refused
  the attack framing on every prompt variant, including fully abstract ones
  with no code/payload (git log: `34f2992`, pitch deck slide 8). Fable then
  went on to write the verdict engine itself (slide 8b) — used in the pitch
  as evidence this is a policy line, not a capability gap.
- **CI/pre-commit bypass gate** added (`03d30ea`) so a found bypass can't
  silently regress.
- **Branch protection unavailable** on this private repo under a free GitHub
  account (HTTP 403, confirmed 2026-09-19) — enforcement is by agreement via
  `CODEOWNERS` (caleb-kylib reviews every PR) until the repo goes public or
  moves to GitHub Pro.
- **Pitch deck content** finalized in `PITCH.md` — 10 slides + demo script +
  anticipated judge Q&A, including the live refusal demo
  (`run.py sql_cleaner --show-refusal`) with a scripted fallback to
  `run.py --fixture` if the network/live call misbehaves.

## Verified working right now

- `.venv/bin/python -m pytest -q` → 129 passed, offline, no API key needed.
- `.venv/bin/python run.py --fixture` → replays the bundled demo in the
  browser, no API key needed.
- Live attack path (`run.py sql_cleaner --show-refusal`) requires
  `ANTHROPIC_API_KEY` in `.env` (gitignored, not verified in this pass since
  it costs live API calls — see SETUP.md for the workspace-scoped key note).

## Open items / not yet done

- Team names in `PITCH.md` Slide 1 (`Team: [names]`) still a placeholder.
- Live demo (`--show-refusal`) hasn't been re-rehearsed since the last
  commit in this session — worth a dry run before presenting.
- `CONTRACT.md` §0 "Stop rule" agreement line (`Agreed? → yes/no`) is still
  unfilled in the doc itself (the team clearly proceeded past Phase 0 given
  the finished build, but the doc wasn't updated to reflect that).

## Where to look next

- [README.md](README.md) — quick start + architecture overview.
- [CONTRACT.md](CONTRACT.md) — team ownership, folder contracts, wire format.
- [SETUP.md](SETUP.md) — hands-on guide, including how to plug in your own
  guard function.
- [PITCH.md](PITCH.md) — full slide deck content + demo script for judges.
