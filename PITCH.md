# LoopHole — pitch deck content

Copy each section into one slide (Slides/Canva/PDF — whatever the judges can
open). Titles are slide titles. Bullets are slide content, kept short on
purpose — say the rest out loud. Speaker notes tell you what to say and when to
run the live demo.

---

## Slide 1 — Title

**LoopHole**
*Find the input that breaks your security check — before an attacker does.*

Team: [names] · Track: Everyday

---

## Slide 2 — The problem, in one picture

**We all ship checks we only tested with normal input.**

- You write a small function whose one job is: block bad input, let good input through.
- You test it with normal, polite input. Of course it passes.
- You never once tried a *sneaky* input — because thinking like an attacker isn't your job.

> Speaker note: ask the room "raise your hand if you've written one of these and
> never tried to break it yourself." Most hands go up or stay down honestly —
> either way, it lands.

---

## Slide 3 — A concrete example (the one we demo)

**The check:** before a database lookup, block anything that looks like SQL injection.

```python
def sql_cleaner(user_input):
    if "'" in user_input: return False      # blocked
    if ";" in user_input: return False      # blocked
    if " or " in user_input.lower(): return False   # blocked
    return True                              # allowed through
```

Looks reasonable. It **does** catch the textbook attack: `1 OR 1=1` — blocked.

> Speaker note: let this sit for a second. "Looks solid, right? That's exactly
> the trap."

---

## Slide 4 — The hole nobody sees by eye

The check only recognizes " or " with a literal space on each side. But a
database treats other characters as whitespace too:

| Input | Guard's check | What the database sees |
|---|---|---|
| `1 OR 1=1` | contains `" or "` → **blocked** | (never reaches the DB) |
| `1⏎OR 1=1` (newline instead of space) | no literal `" or "` → **allowed** | `WHERE id = 1 OR 1=1` → always true |
| `1/**/OR/**/1=1` (SQL comment as a space) | no literal `" or "` → **allowed** | same — always true |

**One invisible character swap, and every row in the table leaks.**

---

## Slide 5 — What we built

**LoopHole: an AI-driven loop that finds this automatically, then proves it, then fixes it.**

Four steps, one shared log file:

1. **Attack** — a model reads the guard's code and proposes sneaky inputs, learning from what got blocked.
2. **Verify** — an independent check re-runs the input and confirms it *actually* breaks in — not just a suspicious-looking string.
3. **Show** — the exact input, why it works, and the one-line fix, live on screen.
4. **Lock it in** — a CI check makes sure that bug can never come back.

> Speaker note: this is where you run `run.py sql_cleaner` live. See "Demo
> script" below for exact timing.

---

## Slide 6 — Why "verify" matters (this is the trust part)

A chatbot can *guess* your code has a bug. It never runs anything.

LoopHole **actually executes** the input against a real database and checks: did
this genuinely leak data, or did it just look scary and fail?

In our own test run: the tool tried several odd inputs that got past the guard,
and **correctly threw out 5 of them as false alarms** before confirming the
real ones. That's proof, not a guess.

---

## Slide 7 — Live demo

*(No slide content — this is where you switch to the terminal/browser.)*

Run: `.venv/bin/python run.py sql_cleaner --show-refusal`

See "Demo script" section below for the exact beats and what to say.

---

## Slide 8 — A finding we didn't expect

We first tried to use **Fable 5.1**, Anthropic's most capable model, as the
attacker.

**It refuses.** Every time, on every framing — even fully abstract ones with no
code and no payload, just "in general, how do blocklist validators fail?" Its
safety training treats the entire topic of "how might this check be bypassed"
as too close to real hacking to help with, regardless of intent.

So we route the bounded, verified task to **Sonnet 5**, which completes it
responsibly — the input never leaves a sandboxed, oracle-checked pipeline.

> Speaker note: this shows the judges you actually evaluated the frontier
> model and made a real engineering call, instead of just picking a model
> name for the pitch.

---

## Slide 8b — Fable 5.1 built part of this system

Refusing to attack isn't the same as being less capable — it's a different
question entirely. And we don't have to guess where Fable stands on
capability: **it's in our own commit history.**

Fable 5.1 wrote our **verdict engine** — the code that decides whether a
bypass is real — including the subtlest part of the whole pipeline:

- **Restart-safe, in order, exactly once.** If the judge restarts mid-run, it
  must not re-judge an input twice or skip one — it counts existing verdicts
  per input and picks up exactly where it left off.
- **A completion protocol most people get wrong on the first try.** The
  attacker can finish generating *before* the judge finishes ruling — so
  "done" doesn't mean "no more writes." The judge guarantees every candidate
  gets a verdict even after the attacker has already stopped.
- **Nothing is ever silently dropped** — malformed data gets reported, never
  swallowed.

That's exactly the kind of long-horizon, correctness-under-edge-cases
reasoning Fable is built for. **It drew a hard line at playing attacker, and
did its best work on the part of the system that keeps the tool honest.**

> Speaker note: this is the strongest Fable slide — it's not "we asked and it
> said no," it's "here's real code it wrote, and it's the hardest part."

---

## Slide 9 — Why this matters beyond one demo

- **Every dev has this problem.** Path checks, login redirects, input cleaners — same story, different guard.
- **It fits into how teams already work.** One command to test a check; a CI check (GitHub Actions) that blocks a broken guard from ever merging again.
- **It's not a toy.** 129 automated tests, a working pipeline, a real GitHub repo — [github.com/Atthespice/LoopHole](https://github.com/Atthespice/LoopHole).

---

## Slide 10 — Try it

```
git clone https://github.com/Atthespice/LoopHole
cd LoopHole && python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py --fixture     # see it work, no API key needed
```

**LoopHole: paste your check, run one command, get the exact input that breaks
it, the fix, and a gate that keeps it fixed — proven by running your code, not
by guessing.**

---

## Demo script (for the live slide)

Run this from the repo root, key already in `.env`:

```
.venv/bin/python run.py sql_cleaner --show-refusal
```

| Time | What happens on screen | What you say |
|---|---|---|
| 0:00 | "Asking claude-fable-5-1..." → **REFUSED** | "We tried the newest model first. It refuses — even to test your own code." |
| 0:10 | Attempts start scrolling (Sonnet 5) | "So the loop uses a model that will do the bounded, verified task." |
| 0:40 | Some inputs ALLOWED, verdict rules some out | "Not every weird input is a real bug — it's checking, not guessing." |
| 1:00 | **REAL BYPASS CONFIRMED** panel | "There it is — the exact input, why it works, the one-line fix." |
| 1:15 | Fix re-run: blocked / safe inputs still pass | "Fix applied, bug's gone, nothing else broke." |

**Fallback if the live run misbehaves (flaky network, rate limit):**
```
.venv/bin/python run.py --fixture
```
Same screen, no API call, cannot fail. Rehearse switching to this once so it's
not a scramble if you need it.

---

## Anticipated judge questions (have an answer ready)

- **"Why not just ask Claude in a chat to review this?"** → A chat gives one
  opinion and stops. We *run* the code, hundreds of times if needed, and
  *prove* the bug reaches a real resource — that's the "verify" step, not the
  "attack" step. Point at slide 6.
- **"Why doesn't Fable power the attack?"** → It refuses on safety grounds,
  even for fully abstract questions with no code and no payload — we tested
  that directly (slide 8). That's a policy line, not a capability gap: Fable
  wrote our verdict engine, the hardest-to-get-right part of the pipeline
  (slide 8b) — check the git history, `Co-Authored-By: Claude Fable 5.1` is
  right there on those commits.
- **"Isn't 'the newer model is worse at your task' bad for you?"** → It's
  worse at *this one adversarial framing* by design, not in general — same
  model, same session, wrote the more architecturally demanding code
  elsewhere in the repo. Capability and safety judgment are different axes;
  we'd rather show you a model with both than one that attacks anything asked
  of it.
- **"Does this scale to a whole codebase?"** → Not automatically — each guard
  needs a human to define what "actually dangerous" means for that specific
  check (the oracle). It's built for testing the checks that matter most, not
  a blind scan of everything.
- **"What's mocked vs real?"** → Say plainly: the pipeline, the guards, the
  verification, the CI gate — all real and tested. The browser view replays a
  finished run rather than streaming strictly concurrently with the attack —
  visually identical, worth mentioning if asked directly.
