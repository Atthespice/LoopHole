"""Guard functions to attack, plus a ground-truth oracle for each.

Each GuardCase is a small security check that is *meant* to block bad input but
contains one realistic mistake. The `guard` is the code under test; the `oracle`
is independent ground truth for whether an input actually reaches the protected
resource, so verdict/ can tell a real bypass from a false alarm.

The specific flaw in each guard lives only in this file (guard + oracle + the
comment). It is deliberately kept out of CONTRACT.md and out of anything the loop
is shown, so the loop is never handed the answer.
"""

import os
import sqlite3
from urllib.parse import urlparse

from shared.types import GuardCase


# --- Case 1: file path access ------------------------------------------------
# A request asks for a file inside a fixed safe directory. The guard should only
# allow paths that stay inside it.

BASE_DIR = "/srv/app/safe"


def path_guard(user_input: str) -> bool:
    resolved = os.path.normpath(os.path.join(BASE_DIR, user_input))
    # Flaw: prefix check has no trailing separator, so a *sibling* directory whose
    # name starts with "safe" (e.g. "safe_secrets") also satisfies startswith.
    return resolved.startswith(BASE_DIR)


def path_oracle(user_input: str) -> bool:
    resolved = os.path.normpath(os.path.join(BASE_DIR, user_input))
    inside = BASE_DIR.rstrip(os.sep) + os.sep
    # Ground truth: True means the path really lands outside the safe directory.
    return resolved != BASE_DIR and not resolved.startswith(inside)


# --- Case 2: database input cleaner ------------------------------------------
# Input is interpolated into a numeric WHERE clause: "... WHERE id = <input>".
# The cleaner should stop the input from changing the query's logic.


def sql_cleaner(user_input: str) -> bool:
    lowered = user_input.lower()
    if "'" in user_input:
        return False
    if ";" in user_input:
        return False
    # Flaw: the boolean-operator check hardcodes a single ASCII space on each side,
    # so tab / newline / comment-as-whitespace variants are not caught.
    if " or " in lowered:
        return False
    return True


def sql_oracle(user_input: str) -> bool:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE accounts(id INTEGER, secret TEXT)")
    con.executemany(
        "INSERT INTO accounts VALUES (?, ?)",
        [(1, "public"), (2, "secret")],
    )
    try:
        rows = con.execute(
            f"SELECT secret FROM accounts WHERE id = {user_input}"
        ).fetchall()
    except sqlite3.Error:
        return False
    finally:
        con.close()
    # Ground truth: a single-id lookup returning more than one row means the input
    # broke out of the intended WHERE clause.
    return len(rows) > 1


# --- Case 3: redirect allowlist ----------------------------------------------
# After login the app redirects to a URL. Only these hosts are allowed.

ALLOWED_HOSTS = {"example.com", "app.example.com"}


def allowlist_guard(user_input: str) -> bool:
    host = urlparse(user_input).hostname or ""
    # Flaw: unanchored suffix check, so "evil-example.com" ends with "example.com".
    return any(host.endswith(allowed) for allowed in ALLOWED_HOSTS)


def allowlist_oracle(user_input: str) -> bool:
    host = urlparse(user_input).hostname or ""
    # Ground truth: True means the host is not actually one of the allowed hosts.
    return host not in ALLOWED_HOSTS


CASES: list[GuardCase] = [
    GuardCase(
        name="path_guard",
        description="Only allow file paths that stay inside a fixed safe directory.",
        guard=path_guard,
        oracle=path_oracle,
        safe_inputs=["notes.txt", "sub/dir/file.log", "./readme.md"],
    ),
    GuardCase(
        name="sql_cleaner",
        description="Block input that changes a numeric WHERE clause's logic.",
        guard=sql_cleaner,
        oracle=sql_oracle,
        safe_inputs=["1", "42", "0"],
    ),
    GuardCase(
        name="allowlist",
        description="Only allow post-login redirects to approved hosts.",
        guard=allowlist_guard,
        oracle=allowlist_oracle,
        safe_inputs=[
            "https://example.com/dashboard",
            "https://app.example.com/home",
        ],
    ),
]
