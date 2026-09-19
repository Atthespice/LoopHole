"""Ready-made oracles for the common guard categories.

The oracle is the honest judge: given an input, is it TRULY dangerous? Writing
one by hand is the hard part of testing an external guard. For the three
categories that have a standard definition of "truly dangerous", you don't have
to: pick a category, give its one setting, and `make_case` wires the oracle for
you. That collapses the 5 GuardCase fields down to 3 you actually fill in
(guard, safe_inputs, and which category), for these cases.

Categories:
  "path"           did the input resolve OUTSIDE the safe folder?
  "sql_numeric"    did the input turn a single-id lookup into a multi-row leak?
  "host_allowlist" is the input's host NOT actually on the allowed list?

If a guard doesn't fit one of these, write the oracle by hand (see the template
in cases.py) -- only you know what "truly dangerous" means for a novel check.
"""

import os
import sqlite3
from urllib.parse import urlparse

from shared.types import GuardCase


def path_escape_oracle(safe_root: str):
    """True when `user_input` resolves outside `safe_root`."""
    root = os.path.normpath(safe_root)

    def oracle(user_input: str) -> bool:
        resolved = os.path.normpath(os.path.join(root, user_input))
        inside = root.rstrip(os.sep) + os.sep
        return resolved != root and not resolved.startswith(inside)

    return oracle


def sql_numeric_oracle(seed_rows=None):
    """True when `user_input`, dropped into `WHERE id = <input>`, returns more
    than one row -- i.e. it broke out of a single-id lookup. Runs against a
    throwaway in-memory database, so nothing real is touched."""
    rows = seed_rows or [(1, "public"), (2, "secret")]

    def oracle(user_input: str) -> bool:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE accounts(id INTEGER, secret TEXT)")
        con.executemany("INSERT INTO accounts VALUES (?, ?)", rows)
        try:
            result = con.execute(
                f"SELECT secret FROM accounts WHERE id = {user_input}"
            ).fetchall()
        except sqlite3.Error:
            return False
        finally:
            con.close()
        return len(result) > 1

    return oracle


def host_allowlist_oracle(allowed_hosts):
    """True when the input's host is not exactly one of `allowed_hosts`."""
    allowed = set(allowed_hosts)

    def oracle(user_input: str) -> bool:
        host = urlparse(user_input).hostname or ""
        return host not in allowed

    return oracle


_BUILDERS = {
    "path": ("safe_root", path_escape_oracle),
    "sql_numeric": ("seed_rows", sql_numeric_oracle),
    "host_allowlist": ("allowed_hosts", host_allowlist_oracle),
}


def make_case(*, name, description, guard, safe_inputs, category, **setting):
    """Build a GuardCase with the oracle chosen for you by `category`.

    Example:
        make_case(
            name="their_path_check",
            description="only allow files inside /srv/app/public",
            guard=their_function,
            safe_inputs=["notes.txt", "sub/file.log"],
            category="path", safe_root="/srv/app/public",
        )
    """
    if category not in _BUILDERS:
        raise ValueError(
            f"unknown category {category!r}; pick one of {list(_BUILDERS)} "
            "or write the oracle by hand (see the template in cases.py)."
        )
    arg_name, builder = _BUILDERS[category]
    if category == "sql_numeric":
        oracle = builder(setting.get("seed_rows"))
    else:
        if arg_name not in setting:
            raise ValueError(f"category {category!r} needs {arg_name}=...")
        oracle = builder(setting[arg_name])
    return GuardCase(
        name=name,
        description=description,
        guard=guard,
        oracle=oracle,
        safe_inputs=safe_inputs,
    )
