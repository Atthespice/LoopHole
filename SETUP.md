# LoopHole — setup & how to test your own code

LoopHole breaks a **guard function** — a small piece of code whose job is to
allow or block some input — by finding an input that sneaks past it, proving the
break is real, and showing the one-line fix.

## 1. Install (once)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. Add your key

Create a file named `.env` in the repo root (it is gitignored):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Use a **workspace-scoped** key. If yours is org-scoped, add a second line:
`ANTHROPIC_WORKSPACE_ID=wrkspc_...` (Console → Settings → Workspaces).

## 3. See it work with no key

```bash
.venv/bin/python run.py --fixture      # replays the bundled demo in your browser
.venv/bin/python -m pytest -q          # 125 tests, all offline
```

## 4. Test your OWN code

You describe your guard once, as a `GuardCase`, in `harness/cases.py`. There are
two ways, depending on whether your guard is a common category.

### Easy path — a common category (path / SQL / allowlist)

No oracle to write. Paste your function, pick the category, list a few normal
inputs:

```python
from harness.oracles import make_case
from harness.cases import CASES

def my_path_check(user_input: str) -> bool:      # <-- your code
    ...                                          # return True = allowed through

CASES.append(make_case(
    name="my_path_check",
    description="only allow files inside /srv/app/public",
    guard=my_path_check,
    safe_inputs=["notes.txt", "sub/file.log"],   # must never be flagged
    category="path", safe_root="/srv/app/public",
))
```

Categories: `path` (needs `safe_root`), `sql_numeric`, `host_allowlist`
(needs `allowed_hosts`).

### Full path — anything else

Copy the commented template at the bottom of `harness/cases.py` and fill in the
three TODOs: your `guard`, an `oracle` (the honest judge — returns True when the
input is *truly* dangerous), and a few `safe_inputs`.

**Two rules for the guard:**
- It must return `True = allowed`, `False = blocked`. If your code is the
  opposite, wrap it: `guard=lambda s: not my_blocker(s)`.
- If your code raises or returns a cleaned string instead of a bool, wrap it in
  a 2-line adapter so it returns a bool.

## 5. Run it end to end

```bash
.venv/bin/python run.py my_path_check          # attack, judge, open browser
.venv/bin/python run.py my_path_check --budget 8   # fewer model calls (cheaper)
.venv/bin/python run.py my_path_check --no-web     # terminal only
```

You get: the exact input that broke your check, proof it's real, and the
one-line fix — in the browser and the terminal.
