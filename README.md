# LoopHole

LoopHole breaks your own security **guard functions** before an attacker does. You
give it a small check meant to block bad input; it uses the newest model (Fable
5.1) to find an input that slips past, proves the break is real by running your
code, and shows the one line that closes the hole.

## Quick start

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python run.py --fixture        # see it work in the browser, no API key
.venv/bin/python -m pytest -q            # 129 offline tests
```

To attack a real guard, add your `ANTHROPIC_API_KEY` to a `.env` file and run
`.venv/bin/python run.py <case>`. Full walkthrough — including how to test your
own code — in [SETUP.md](SETUP.md).

## How it works

Four parts talk only through one run-log file (`runs/<case>.jsonl`); none imports
another's code:

- **harness/** — the guard functions to attack, each with an *oracle* (ground
  truth for "did this input really get through?").
- **loop/** — the attacker: asks the model for an input, runs it against the
  guard, learns from the result, repeats.
- **verdict/** — the judge: confirms a candidate is a *real* bypass, not a false
  alarm, and writes the one-line fix.
- **demo/** — the live screen the room watches (terminal). `web/` mirrors it in a
  browser.

## Keep guards fixed (CI)

A live attack *finds* a bypass; the gate *keeps* it fixed. Discover once, then
`harness/check.py` re-checks guards against recorded bypasses on every push/PR —
keyless and deterministic (`.github/workflows/ci.yml`, `hooks/pre-commit`).

## For the team

Start with [CONTRACT.md](CONTRACT.md) — folder ownership, the go/no-go gates, and
the shared data shapes. [SETUP.md](SETUP.md) is the hands-on guide.

Never commit `.env` — it holds your API key (see `.gitignore`).
