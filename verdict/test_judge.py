"""Tests for verdict/judge.py. Uses a fixture GuardCase (no harness/ dependency)
so verdict/ can be tested before harness/ ships its real cases."""

import io
import json
import posixpath
import unicodedata

import pytest

from shared.types import Candidate, GuardCase
from verdict.judge import judge, suggest_fix, tail_and_judge

ROOT = "/srv/files"


def _resolve(p: str) -> str:
    # ground truth: what the filesystem would actually open
    p = unicodedata.normalize("NFKC", p).replace("\\", "/")
    return posixpath.normpath(posixpath.join(ROOT, p))


def _guard(p: str) -> bool:
    # deliberately weak: blocks literal ".." and absolute paths only, so a
    # fullwidth "．．" slips through
    return ".." not in p and not p.startswith("/")


def _oracle(p: str) -> bool:
    return not _resolve(p).startswith(ROOT + "/")


@pytest.fixture
def case() -> GuardCase:
    return GuardCase(
        name="path_traversal",
        description="path traversal check under /srv/files",
        guard=_guard,
        oracle=_oracle,
        safe_inputs=["readme.txt", "docs/guide.md"],
    )


def cand(case, s, idx=0):
    return Candidate(case_name=case.name, input=s, attempt_index=idx)


def test_real_bypass_confirmed(case):
    v = judge(case, cand(case, "．．/．．/etc/passwd"))
    assert v.is_real_bypass
    assert v.case_name == case.name
    assert "Confirmed real bypass" in v.explanation
    assert "NFKC" in v.suggested_fix


def test_guard_blocks_means_not_reproducible(case):
    v = judge(case, cand(case, "../etc/passwd"))
    assert not v.is_real_bypass
    assert "does not reproduce" in v.explanation


def test_safe_input_is_never_a_bypass(case):
    v = judge(case, cand(case, "readme.txt"))
    assert not v.is_real_bypass
    assert "safe_inputs" in v.explanation


def test_passes_guard_but_oracle_says_harmless(case):
    v = judge(case, cand(case, "docs/other.md"))
    assert not v.is_real_bypass
    assert "false alarm" in v.explanation


def test_case_name_mismatch_refuses(case):
    v = judge(case, Candidate(case_name="other", input="x", attempt_index=0))
    assert not v.is_real_bypass
    assert "mismatched" in v.explanation


def test_guard_crash_is_not_a_bypass():
    def boom(_):
        raise ValueError("nope")

    case = GuardCase("c", "crashy", guard=boom, oracle=lambda s: True, safe_inputs=[])
    v = judge(case, Candidate("c", "anything", 0))
    assert not v.is_real_bypass
    assert "crashed" in v.explanation
    assert "fail closed" in v.suggested_fix


def test_oracle_crash_is_not_a_bypass():
    def boom(_):
        raise RuntimeError("nope")

    case = GuardCase("c", "crashy", guard=lambda s: True, oracle=boom, safe_inputs=[])
    v = judge(case, Candidate("c", "anything", 0))
    assert not v.is_real_bypass
    assert "Oracle crashed" in v.explanation


@pytest.mark.parametrize(
    "value, needle",
    [
        ("a\x00b", "NUL"),
        ("%252e%252e/", "repeatedly"),
        ("%2e%2e/x", "decode"),
        ("..\\..\\x", "backslash"),
        ("  admin", "whitespace"),
        ("' OR 1=1 --", "parameterized"),
        ("evil.com@good.com", "hostname"),
    ],
)
def test_suggest_fix_matches_input_shape(value, needle):
    case = GuardCase("generic", "a guard", guard=lambda s: True, oracle=lambda s: True, safe_inputs=[])
    assert needle.lower() in suggest_fix(case, value).lower()


def test_suggest_fix_falls_back_on_case_description():
    case = GuardCase("db_clean", "DB input cleaner", guard=lambda s: True, oracle=lambda s: True, safe_inputs=[])
    assert "parameterized" in suggest_fix(case, "plain")


def test_tail_and_judge_appends_verdicts(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    events = [
        {"kind": "attempt", "payload": {"case_name": case.name, "input": "x", "guard_result": True}},
        {"kind": "candidate", "payload": {"case_name": case.name, "input": "．．/etc/passwd", "attempt_index": 3}},
        {"kind": "candidate", "payload": {"case_name": case.name, "input": "readme.txt", "attempt_index": 4}},
        {"kind": "candidate", "payload": {"case_name": case.name, "input": "readme.txt", "attempt_index": 5}},  # dup
        {"kind": "done"},
    ]
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    out = io.StringIO()
    verdicts = tail_and_judge(case, str(log), poll=0.01, out=out)

    assert [v.is_real_bypass for v in verdicts] == [True, False]
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert all(line["kind"] == "verdict" for line in lines)
    assert lines[0]["payload"]["is_real_bypass"] is True
    assert lines[0]["payload"]["suggested_fix"]
    assert set(lines[0]["payload"]) == {"case_name", "input", "is_real_bypass", "explanation", "suggested_fix"}


def test_tail_and_judge_default_sink_appends_to_log(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    events = [
        {"kind": "candidate", "payload": {"case_name": case.name, "input": "docs/other.md", "attempt_index": 0}},
        {"kind": "done"},
    ]
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    tail_and_judge(case, str(log), poll=0.01)
    kinds = [json.loads(line)["kind"] for line in log.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["candidate", "done", "verdict"]


def test_tail_and_judge_skips_already_judged(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    events = [
        {"kind": "candidate", "payload": {"case_name": case.name, "input": "readme.txt", "attempt_index": 0}},
        {"kind": "verdict", "payload": {"case_name": case.name, "input": "readme.txt", "is_real_bypass": False,
                                        "explanation": "already", "suggested_fix": "n/a"}},
        {"kind": "done"},
    ]
    log.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    assert tail_and_judge(case, str(log), poll=0.01, out=io.StringIO()) == []
