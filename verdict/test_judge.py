"""Tests for verdict/judge.py. Uses a fixture GuardCase (no harness/ dependency)
so verdict/ can be tested before harness/ ships its real cases."""

import io
import json
import posixpath
import unicodedata

import pytest

from shared.types import Candidate, GuardCase
from verdict.judge import judge, load_case, main, suggest_fix, tail_and_judge

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


BYPASS = "．．/etc/passwd"

# Module-level so load_case() can import it via "verdict.test_judge:FIXTURE_CASES".
FIXTURE_CASES: list[GuardCase] = [
    GuardCase(
        name="path_traversal",
        description="path traversal check under /srv/files",
        guard=_guard,
        oracle=_oracle,
        safe_inputs=["readme.txt", "docs/guide.md"],
    )
]


@pytest.fixture
def case() -> GuardCase:
    return FIXTURE_CASES[0]


def cand(case, s, idx=0):
    return Candidate(case_name=case.name, input=s, attempt_index=idx)


def ev(kind, **payload):
    return {"kind": kind, "payload": payload} if payload else {"kind": kind}


def candidate_ev(case, s, idx):
    return ev("candidate", case_name=case.name, input=s, attempt_index=idx)


def write_log(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- judge() ------------------------------------------------------------------


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


# --- suggest_fix() --------------------------------------------------------------


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


# --- tail_and_judge(): wire format --------------------------------------------------


def test_one_verdict_per_candidate_event_even_for_repeated_input(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    write_log(log, [
        ev("attempt", case_name=case.name, input="x", guard_result=True),
        candidate_ev(case, BYPASS, 3),
        candidate_ev(case, "readme.txt", 4),
        candidate_ev(case, "readme.txt", 5),  # same input, different attempt
        ev("done"),
    ])

    out = io.StringIO()
    res = tail_and_judge(case, str(log), poll=0.01, out=out)

    assert res.errors == []
    assert [v.is_real_bypass for v in res.verdicts] == [True, False, False]
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [line["kind"] for line in lines] == ["verdict"] * 3
    assert lines[0]["payload"]["is_real_bypass"] is True
    assert lines[0]["payload"]["suggested_fix"]
    assert set(lines[0]["payload"]) == {"case_name", "input", "is_real_bypass", "explanation", "suggested_fix"}


def test_every_candidate_has_a_verdict_when_tailer_returns(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    write_log(log, [
        candidate_ev(case, "docs/other.md", 0),
        candidate_ev(case, BYPASS, 1),
        ev("done"),
    ])
    tail_and_judge(case, str(log), poll=0.01)
    events = read_events(log)
    kinds = [e["kind"] for e in events]
    assert kinds == ["candidate", "candidate", "done", "verdict", "verdict"]
    # completion protocol: #verdicts == #candidates once the judge is finished
    assert kinds.count("verdict") == kinds.count("candidate")


def test_restart_skips_exactly_the_already_judged_events(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    write_log(log, [
        candidate_ev(case, "readme.txt", 0),
        candidate_ev(case, "readme.txt", 1),
        ev("verdict", case_name=case.name, input="readme.txt", is_real_bypass=False,
           explanation="already", suggested_fix="n/a"),
        candidate_ev(case, "readme.txt", 2),
        ev("done"),
    ])
    # one prior verdict for "readme.txt" -> skip one candidate event, rule on the other two
    res = tail_and_judge(case, str(log), poll=0.01, out=io.StringIO())
    assert len(res.verdicts) == 2
    assert all(v.input == "readme.txt" for v in res.verdicts)


def test_corrupt_json_is_reported_not_dropped(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    good = json.dumps(candidate_ev(case, BYPASS, 0))
    log.write_text(
        "{not json\n" + good + "\n" + "[1, 2]\n" + json.dumps(ev("done")) + "\n",
        encoding="utf-8",
    )
    seen = []
    res = tail_and_judge(case, str(log), poll=0.01, out=io.StringIO(), on_error=seen.append)

    assert len(res.verdicts) == 1 and res.verdicts[0].is_real_bypass
    assert [e.line_no for e in res.errors] == [1, 3]
    assert "corrupt JSON" in res.errors[0].reason
    assert "not an object" in res.errors[1].reason
    assert seen == res.errors  # on_error was called for each


def test_malformed_candidate_payload_gets_a_verdict_and_an_error(case, tmp_path):
    log = tmp_path / "path_traversal.jsonl"
    write_log(log, [
        {"kind": "candidate", "payload": {"case_name": case.name, "input": BYPASS}},   # no attempt_index
        {"kind": "candidate", "payload": {"case_name": case.name, "input": 42, "attempt_index": 1}},
        {"kind": "candidate", "payload": "nope"},
        {"kind": "candidate"},
        ev("done"),
    ])
    out = io.StringIO()
    res = tail_and_judge(case, str(log), poll=0.01, out=out, on_error=lambda e: None)

    assert len(res.errors) == 4
    assert all("malformed candidate" in e.reason for e in res.errors)
    assert "attempt_index" in res.errors[0].reason
    # the one with a usable input still gets a (not-a-bypass) verdict on the wire
    assert len(res.verdicts) == 1
    assert res.verdicts[0].input == BYPASS
    assert res.verdicts[0].is_real_bypass is False
    assert "Malformed candidate" in res.verdicts[0].explanation
    assert json.loads(out.getvalue())["kind"] == "verdict"


def test_default_on_error_writes_to_stderr(case, tmp_path, capsys):
    log = tmp_path / "path_traversal.jsonl"
    log.write_text("garbage\n" + json.dumps(ev("done")) + "\n", encoding="utf-8")
    tail_and_judge(case, str(log), poll=0.01, out=io.StringIO())
    assert "line 1" in capsys.readouterr().err


# --- CLI: case is injected, not imported ------------------------------------------


def test_load_case_from_module_spec():
    c = load_case("verdict.test_judge:FIXTURE_CASES", "path_traversal")
    assert c is FIXTURE_CASES[0]


def test_load_case_unknown_name_exits():
    with pytest.raises(SystemExit):
        load_case("verdict.test_judge:FIXTURE_CASES", "nope")


def test_cli_end_to_end(case, tmp_path, capsys):
    log = tmp_path / "path_traversal.jsonl"
    write_log(log, [candidate_ev(case, BYPASS, 0), ev("done")])
    rc = main(["path_traversal", "--cases", "verdict.test_judge:FIXTURE_CASES", "--log", str(log)])
    assert rc == 0
    assert "REAL BYPASS" in capsys.readouterr().out
    assert [e["kind"] for e in read_events(log)] == ["candidate", "done", "verdict"]
