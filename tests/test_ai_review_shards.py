"""
How the AI review splits a PR into parts (scripts/ai_review_shards.py).

Each source file is reviewed beside its own tests, parts are small
enough that one review's cap of findings isn't spent before the end,
and prose docs (the changelog, the plan) are left out by name.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location("ai_review_shards", _SCRIPTS / "ai_review_shards.py")
shards = importlib.util.module_from_spec(_spec)
sys.modules["ai_review_shards"] = shards
_spec.loader.exec_module(shards)


def _file(path: str, size: int = 10) -> "shards.FileDiff":
    return shards.FileDiff(path=path, text="x" * size)


# ── which files are read ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["docs/changelog.md", "tasks/todo.md", "tasks/owner-todo.md", "README.md",
     "frontend/README.md", "docs/testing.md", "docs/deployment.md"],
)
def test_prose_docs_are_left_out(path):
    assert shards.is_prose_doc(path)


@pytest.mark.parametrize(
    "path",
    ["CLAUDE.md", "docs/security.md", "docs/adr/0009-tastytrade-live-personal.md",
     "app/services/trade_journal.py", "frontend/src/lib/journal-text.ts", ".github/workflows/ci.yml"],
)
def test_rules_and_code_are_reviewed(path):
    # CLAUDE.md, the security doc and ADRs hold rules a change can break.
    assert not shards.is_prose_doc(path)


@pytest.mark.parametrize(
    ("path", "whole"),
    [("app/services/trade_journal.py", True), ("frontend/src/components/trades/JournalView.tsx", True),
     ("frontend/src/lib/journal-text.ts", True), ("scripts/ai_review.py", True),
     ("tests/test_trade_journal.py", False), ("frontend/src/lib/journal-text.test.ts", False),
     ("CLAUDE.md", False), (".github/workflows/ci.yml", False), ("pyproject.toml", False)],
)
def test_whole_function_context_for_source_code_only(path, whole):
    # Tests and config keep three lines: whole functions would double them.
    assert shards.wants_function_context(path) is whole


# ── review units: a source file with its tests ───────────────────────


def test_a_python_service_is_read_with_its_test_file():
    files = [_file("tests/test_trade_journal.py"), _file("app/services/trade_journal.py")]
    units = shards.review_units(files)
    assert [[f.path for f in u] for u in units] == [
        ["app/services/trade_journal.py", "tests/test_trade_journal.py"]
    ]


def test_a_component_and_a_lib_file_are_read_with_their_tests():
    files = [
        _file("frontend/src/components/trades/JournalView.tsx"),
        _file("frontend/src/lib/journal-text.test.ts"),
        _file("frontend/src/components/trades/JournalView.test.tsx"),
        _file("frontend/src/lib/journal-text.ts"),
    ]
    units = shards.review_units(files)
    assert [[f.path for f in u] for u in units] == [
        ["frontend/src/components/trades/JournalView.tsx", "frontend/src/components/trades/JournalView.test.tsx"],
        ["frontend/src/lib/journal-text.ts", "frontend/src/lib/journal-text.test.ts"],
    ]


def test_files_without_a_partner_stand_alone_in_path_order():
    files = [_file("tests/test_owner_auth.py"), _file("app/main.py"), _file("CLAUDE.md")]
    units = shards.review_units(files)
    assert [[f.path for f in u] for u in units] == [["CLAUDE.md"], ["app/main.py"], ["tests/test_owner_auth.py"]]


def test_a_test_pairs_with_one_source_when_two_share_its_name():
    files = [_file("app/schemas/owner.py"), _file("app/api/v1/routers/owner.py"), _file("tests/test_owner.py")]
    units = shards.review_units(files)
    paired = [u for u in units if len(u) == 2]
    assert len(paired) == 1 and paired[0][1].path == "tests/test_owner.py"


# ── packing units into parts ─────────────────────────────────────────


def test_units_fill_parts_in_order_up_to_the_size():
    units = [[_file("a.py", 40)], [_file("b.py", 40)], [_file("c.py", 40)]]
    parts, over = shards.pack(units, part_chars=100, max_parts=5)
    assert [[f.path for f in p] for p in parts] == [["a.py", "b.py"], ["c.py"]]
    assert over == []


def test_a_unit_too_big_for_a_part_is_split_into_its_files():
    units = [[_file("a.py", 80), _file("tests/test_a.py", 80)]]
    parts, over = shards.pack(units, part_chars=100, max_parts=5)
    assert [[f.path for f in p] for p in parts] == [["a.py"], ["tests/test_a.py"]]


def test_a_file_bigger_than_a_part_gets_a_part_of_its_own():
    units = [[_file("small.py", 10)], [_file("big.py", 150)], [_file("next.py", 10)]]
    parts, over = shards.pack(units, part_chars=100, max_parts=5)
    assert [[f.path for f in p] for p in parts] == [["small.py"], ["big.py"], ["next.py"]]


def test_over_the_part_limit_tests_go_first():
    units = [[_file("a.py", 60), _file("tests/test_a.py", 60)], [_file("b.py", 60), _file("tests/test_b.py", 60)]]
    parts, over = shards.pack(units, part_chars=100, max_parts=2)
    assert [[f.path for f in p] for p in parts] == [["a.py"], ["b.py"]]
    assert over == ["tests/test_a.py", "tests/test_b.py"]


def test_over_the_part_limit_without_tests_the_last_parts_are_named():
    units = [[_file("a.py", 90)], [_file("b.py", 90)], [_file("c.py", 90)]]
    parts, over = shards.pack(units, part_chars=100, max_parts=2)
    assert [[f.path for f in p] for p in parts] == [["a.py"], ["b.py"]]
    assert over == ["c.py"]


def test_plan_names_generated_and_docs_and_parts_the_rest():
    files = [_file("uv.lock"), _file("docs/changelog.md"), _file("app/a.py"), _file("tests/test_a.py")]
    plan = shards.plan_parts(files, part_chars=100, max_parts=4)
    assert plan.generated == ["uv.lock"]
    assert plan.docs == ["docs/changelog.md"]
    assert [[f.path for f in p] for p in plan.parts] == [["app/a.py", "tests/test_a.py"]]
    assert plan.over_budget == []


def test_plan_of_docs_only_has_no_parts():
    plan = shards.plan_parts([_file("tasks/todo.md")], part_chars=100, max_parts=4)
    assert plan.parts == [] and plan.docs == ["tasks/todo.md"]


# ── the diff, split per file ─────────────────────────────────────────


def _diff(path: str, body: str = "+x = 1\n") -> str:
    return (f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,0 +1,1 @@\n{body}")


def test_split_diff_one_entry_per_file_in_order():
    files = shards.split_diff(_diff("app/a.py") + _diff("frontend/src/b.tsx"))
    assert [f.path for f in files] == ["app/a.py", "frontend/src/b.tsx"]


def test_split_diff_reads_the_new_path_of_a_rename():
    diff = ("diff --git a/app/old.py b/app/new.py\nsimilarity index 90%\nrename from app/old.py\n"
            "rename to app/new.py\n")
    assert [f.path for f in shards.split_diff(diff)] == ["app/new.py"]


def test_split_diff_of_nothing_is_empty():
    assert shards.split_diff("") == []


@pytest.mark.parametrize("path", ["uv.lock", "frontend/package-lock.json", "docs/x.png", "a/b.snap"])
def test_generated_and_binary_files_are_left_out(path):
    assert shards.is_generated(path)
