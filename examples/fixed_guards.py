"""The three demo guards, with the fix applied.

These are what the guards in harness/cases.py should have been. The CI gate runs
against these to prove the recorded bypasses are now blocked -- i.e. a correct
guard passes the gate. Point the gate at your own guards the same way:
    python -m harness.check --offline --cases your_module:CASES
"""

import os
from urllib.parse import urlparse

from harness.oracles import make_case

BASE_DIR = "/srv/app/safe"
ALLOWED_HOSTS = ["example.com", "app.example.com"]


def path_guard(user_input: str) -> bool:
    resolved = os.path.normpath(os.path.join(BASE_DIR, user_input))
    # Fix: compare against BASE_DIR + separator, so a sibling like "safe_secrets"
    # no longer satisfies the check.
    return resolved == BASE_DIR or resolved.startswith(BASE_DIR + os.sep)


def sql_cleaner(user_input: str) -> bool:
    # Fix: the value goes into a numeric WHERE clause, so only allow integers.
    # Whitespace/comment tricks are no longer digits, so they're blocked.
    return user_input.strip().isdigit()


def allowlist_guard(user_input: str) -> bool:
    # Fix: exact host match instead of an unanchored suffix.
    return (urlparse(user_input).hostname or "") in set(ALLOWED_HOSTS)


CASES = [
    make_case(
        name="path_guard",
        description="Only allow file paths that stay inside a fixed safe directory.",
        guard=path_guard,
        safe_inputs=["notes.txt", "sub/dir/file.log", "./readme.md"],
        category="path", safe_root=BASE_DIR,
    ),
    make_case(
        name="sql_cleaner",
        description="Block input that changes a numeric WHERE clause's logic.",
        guard=sql_cleaner,
        safe_inputs=["1", "42", "0"],
        category="sql_numeric",
    ),
    make_case(
        name="allowlist",
        description="Only allow post-login redirects to approved hosts.",
        guard=allowlist_guard,
        safe_inputs=["https://example.com/dashboard", "https://app.example.com/home"],
        category="host_allowlist", allowed_hosts=ALLOWED_HOSTS,
    ),
]
