"""
The AI review's second look at each finding (scripts/ai_review_verify.py).

Without thinking, the review in parts found as many real problems as
with it, at a twentieth of the tokens written, but about 60% of what it
raised didn't hold (graded on #128-#131). Each finding is checked
against the whole file it names before it's posted.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
for name in ("ai_review_findings", "ai_review_verify"):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
verify = sys.modules["ai_review_verify"]
Finding = sys.modules["ai_review_findings"].Finding


def _finding(path="app/a.py", line=3):
    return Finding("medium", path, line, "the total ignores refunds", "a refund of 5 makes the total 10, not 0")


def test_messages_put_the_file_before_the_finding_so_findings_on_one_file_share_a_prefix():
    one = verify.build_messages(_finding(line=3), file_text="FILE", file_diff="DIFF")
    two = verify.build_messages(_finding(line=9), file_text="FILE", file_diff="DIFF")
    assert one[0] == two[0]
    prefix = one[1]["content"].split("## The finding")[0]
    assert "FILE" in prefix and "DIFF" in prefix
    assert two[1]["content"].startswith(prefix)
    assert "refunds" in one[1]["content"] and "refunds" not in prefix


def test_the_file_is_numbered_so_the_finding_s_line_can_be_found():
    messages = verify.build_messages(_finding(), file_text="a = 1\nb = 2\n", file_diff="")
    assert "   1  a = 1" in messages[1]["content"] and "   2  b = 2" in messages[1]["content"]


def test_a_big_file_is_cut_to_a_window_around_the_line():
    text = "".join(f"line {i}\n" for i in range(1, 5001))
    window = verify.file_window(text, line=2500, max_lines=400)
    assert "line 2500" in window and "line 2300" in window and "line 2690" in window
    assert "line 1\n" not in window and "line 5000" not in window


def test_a_small_file_is_shown_whole():
    text = "".join(f"line {i}\n" for i in range(1, 51))
    assert verify.file_window(text, line=None, max_lines=400).count("\n") == 50


def test_a_deleted_or_missing_file_says_so():
    messages = verify.build_messages(_finding(), file_text="", file_diff="DIFF")
    assert "isn't in the pull request's head" in messages[1]["content"]


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [({"verdict": "confirmed", "reason": "r"}, "confirmed"),
     ({"verdict": "REFUTED", "reason": "r"}, "refuted"),
     ({"verdict": "maybe", "reason": "r"}, "unsure"),
     ({"reason": "r"}, "unsure")],
)
def test_verdicts(answer, verdict):
    assert verify.parse_verdict(json.dumps(answer))[0] == verdict


def test_an_answer_that_isnt_json_is_unsure():
    # Unsure keeps the finding: a check that fails mustn't hide a real one.
    assert verify.parse_verdict("I think it's fine")[0] == "unsure"
