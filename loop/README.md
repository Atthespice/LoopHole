# loop/ — owner: Mastean12 (see CONTRACT.md section 0)

Owns: the attacking loop.

- Input: a single `GuardCase`, an attempt budget.
- Output: appends `attempt` and `candidate` events to `runs/<case_name>.jsonl`.
- Entry point: `run_loop(case, budget, log_path) -> None`

Must not decide whether a candidate is a *real* break — that's verdict/'s job.
Must not import from verdict/ or demo/. Only imports from `shared/` plus the
approved `anthropic` SDK.

## What it does

The classic generate → run → observe → mutate loop:

1. Ask the model for one candidate input, given every attempt so far.
2. Run it against `case.guard`.
3. Append an `attempt` event; if the guard let it through (`guard_result is True`),
   also append a `candidate` event.
4. Feed the growing history back into the next request so the model adapts.

## Files

- `run_loop.py` — the loop and JSONL logging (`run_loop`, the public entry point).
- `model.py` — the model seam: `AttackModel` protocol, the real
  `AnthropicAttackModel`, `Proposal`, and `ModelRefusal`.
- `test_run_loop.py` — unit tests driven by a fake in-process model.
- `conftest.py` — puts the repo root on `sys.path` for the tests.

## Design notes (choices this folder made within the contract)

- **Model is injected behind a protocol.** `run_loop` uses the real
  anthropic-backed model; tests call the internal `_run_loop(..., model=...)` with
  a fake. So unit tests need no `anthropic` package, no `ANTHROPIC_API_KEY`, and no
  network. The `anthropic` import is lazy — only a live run pulls it in.
- **Refusals are surfaced, never swallowed.** CONTRACT.md Gate 3 is explicit that a
  model refusal must not be mistaken for "no bypass found". A refusal on one attempt
  logs to stderr and moves on; if the model refuses on *every* attempt, `run_loop`
  raises `ModelRefusal` rather than returning a quiet, empty run.
- **A terminal `done` event is emitted.** The wire format in CONTRACT.md lists
  `{"kind": "done"}`, and demo/ tails the log until it lands. The loop is the run's
  producer, so it writes `done` when generation finishes. If the team would rather
  another folder own that marker, it's a one-line change here.
- **Default attack model is `claude-opus-5`** (`model.DEFAULT_MODEL`). Override via
  `AnthropicAttackModel(model=...)` to run the previous-model baseline for Gate 1.

## Running the tests

```
python -m pytest loop/ -q
```
