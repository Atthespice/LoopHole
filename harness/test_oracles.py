"""Tests for the ready-made oracles and make_case. No API key needed."""

import pytest

from harness.oracles import (
    host_allowlist_oracle,
    make_case,
    path_escape_oracle,
    sql_numeric_oracle,
)


def test_path_oracle_flags_escape_only():
    oracle = path_escape_oracle("/srv/app/public")
    assert oracle("../public_backup/id_rsa") is True   # sibling dir, escapes
    assert oracle("../../etc/passwd") is True
    assert oracle("notes.txt") is False                # stays inside
    assert oracle("sub/dir/file.log") is False


def test_sql_oracle_flags_multirow_only():
    oracle = sql_numeric_oracle()
    assert oracle("1 OR 1=1") is True                  # tautology -> many rows
    assert oracle("1") is False                        # single-id lookup
    assert oracle("999") is False                      # no rows
    assert oracle("not-a-number") is False             # errors -> not a bypass


def test_host_allowlist_oracle_flags_offlist_only():
    oracle = host_allowlist_oracle(["example.com", "app.example.com"])
    assert oracle("https://evil-example.com/x") is True
    assert oracle("https://example.com/dashboard") is False
    assert oracle("https://app.example.com/home") is False


def test_make_case_wires_the_oracle():
    def guard(s: str) -> bool:
        return ".." not in s  # naive; allows encoded traversal etc.

    case = make_case(
        name="demo",
        description="only allow files inside the folder",
        guard=guard,
        safe_inputs=["notes.txt"],
        category="path",
        safe_root="/srv/app/public",
    )
    assert case.name == "demo"
    assert case.oracle("../../etc/passwd") is True
    assert case.oracle("notes.txt") is False


def test_make_case_rejects_unknown_category():
    with pytest.raises(ValueError):
        make_case(
            name="x", description="y", guard=lambda s: True,
            safe_inputs=[], category="banana",
        )


def test_make_case_requires_the_setting():
    with pytest.raises(ValueError):
        make_case(
            name="x", description="y", guard=lambda s: True,
            safe_inputs=[], category="path",  # missing safe_root
        )
