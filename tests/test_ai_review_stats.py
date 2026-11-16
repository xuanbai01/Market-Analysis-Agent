"""
How the AI review is doing across PRs (scripts/ai_review_stats.py): its
tokens from the review comment's state, what held from the author's
replies, and what it missed from the changelog.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("ai_review_stats", _SCRIPTS / "ai_review_stats.py")
stats = importlib.util.module_from_spec(_spec)
sys.modules["ai_review_stats"] = stats
_spec.loader.exec_module(stats)
ai_review = sys.modules["ai_review"]


@pytest.mark.parametrize(
    ("body", "held", "not_held"),
    [
        ("<!-- ai-review:reply -->\nHeld: 2, 14, 19\nDidn't hold: 1, 3-5", {2, 14, 19}, {1, 3, 4, 5}),
        ("<!-- ai-review:reply -->\n**Held:** 7 and 9.\n**Didn’t hold:** 20–22", {7, 9}, {20, 21, 22}),
        ("<!-- ai-review:reply -->\nHeld: none\nDidn't hold: 1", set(), {1}),
        ("<!-- ai-review:reply -->\nA reply without the lines.", set(), set()),
    ],
)
def test_a_reply_says_which_findings_held(body, held, not_held):
    assert stats.parse_reply(body) == (held, not_held)


def test_missed_bugs_are_counted_by_the_pr_whose_review_missed_them():
    changelog = ("- a bug found in prod (missed by #140's review)\n"
                 "- another (missed by #140's review); one more (missed by #142's review)\n")
    assert stats.missed_by(changelog) == {140: 2, 142: 1}


def _comment(body, association="OWNER"):
    return {"body": body, "author_association": association}


def test_a_pr_s_row_adds_up_its_reviews_and_replies():
    state = {"sha": "abc", "findings": [],
             "tokens": {"reviews": 3, "read": 160_000, "cached": 55_000, "written": 11_000, "reasoning": 0,
                        "calls": 11}}
    comments = [
        _comment(ai_review.MARKER + "\n### AI review\n" + ai_review.embed_state(state), association="NONE"),
        _comment("<!-- ai-review:reply -->\nHeld: 2, 14\nDidn't hold: 1, 3, 4"),
        _comment("<!-- ai-review:reply -->\nHeld: none\nDidn't hold: 1-3"),
        _comment("<!-- ai-review:reply -->\nHeld: 5", association="NONE"),  # not someone who can push
    ]
    row = stats.pr_row(140, comments, {140: 1})
    assert (row["reviews"], row["read"], row["written"]) == (3, 160_000, 11_000)
    assert (row["held"], row["not_held"], row["missed"]) == (2, 6, 1)
    assert row["held_share"] == pytest.approx(0.25)


def test_a_pr_from_before_the_totals_has_no_token_figures():
    row = stats.pr_row(120, [_comment(ai_review.MARKER + "\nold review", association="NONE")], {})
    assert row["reviews"] is None and row["held_share"] is None


def test_the_table_shows_the_old_review_beside_the_new():
    text = stats.table([stats.pr_row(140, [], {})])
    assert "#128" in text and "#140" in text and "before" in text


@pytest.mark.parametrize(
    ("line", "numbers"),
    [("Held: 2, 14 — 3 of them high", {2, 14}), ("Held: 2 (the 512 MB case), 14", {2}),
     ("Held: 1, 3 and 5-6.", {1, 3, 5, 6}), ("Held: none", set())],
)
def test_only_the_list_at_the_start_of_the_line_counts(line, numbers):
    # Numbers in the reason after the list aren't findings.
    assert stats.parse_reply("<!-- ai-review:reply -->\n" + line)[0] == numbers
