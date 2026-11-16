"""
How the AI review is doing across PRs (dev-only).

For each PR it reads:
- **What the reviews cost:** the review comment's state, where
  ai_review.py keeps the PR's running totals (reviews, tokens).
- **What held:** the author's reply comments (`<!-- ai-review:reply -->`),
  each with a "Held: 2, 14" and a "Didn't hold: 1, 3-5" line.
- **What it missed:** docs/changelog.md, where a bug found after merge in
  code a PR added says "missed by #NNN's review".

It prints them beside the old review on #128-#131 (BEFORE). Run it from
the repo root with `gh` signed in:
  python scripts/ai_review_stats.py --since 135
  python scripts/ai_review_stats.py 136 137 140

What to look for (docs/workflow.md §8): a held share under about one in
five, a missed bug of a kind a lens should catch, fix rounds past three,
or tokens per PR creeping up.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_review  # noqa: E402
from ai_review_findings import REPLY_AUTHORS, REPLY_MARKER  # noqa: E402

# The old review, one whole-PR pass on every push (CI logs and the
# changelog's fix and "Not changed" lists, 2026-11-16).
BEFORE = {
    128: {"reviews": 8, "read": 411_560, "written": 307_858, "held": 20, "not_held": 6},
    129: {"reviews": 11, "read": 462_855, "written": 383_859, "held": 31, "not_held": 8},
    130: {"reviews": 12, "read": 388_249, "written": 449_730, "held": 24, "not_held": 19},
    131: {"reviews": 10, "read": 406_519, "written": 334_432, "held": 24, "not_held": 6},
}

_HELD = re.compile(r"^[\s*_]*held[\s*_]*:[\s*_]*(.*)$", re.I | re.M)
_NOT_HELD = re.compile(r"^[\s*_]*didn['’]t hold[\s*_]*:[\s*_]*(.*)$", re.I | re.M)
_NUMBERS = re.compile(r"(\d+)\s*[-–]\s*(\d+)|(\d+)")
# The list at the start of a line: numbers and ranges joined by commas or
# "and". Numbers in a reason after it aren't findings.
_LIST = re.compile(r"\d+(?:\s*[-–]\s*\d+)?(?:\s*(?:,|and|&)\s*\d+(?:\s*[-–]\s*\d+)?)*")
_MISSED = re.compile(r"missed by #(\d+)['’]s review", re.I)


def _numbers(text: str) -> set[int]:
    listed = _LIST.match(text.strip())
    found: set[int] = set()
    if not listed:
        return found
    for low, high, single in _NUMBERS.findall(listed.group(0)):
        if single:
            found.add(int(single))
        else:
            found.update(range(int(low), int(high) + 1))
    return found


def parse_reply(body: str) -> tuple[set[int], set[int]]:
    """(the finding numbers that held, those that didn't)."""
    held = _HELD.search(body)
    not_held = _NOT_HELD.search(body)
    return (_numbers(held.group(1)) if held else set(), _numbers(not_held.group(1)) if not_held else set())


def missed_by(changelog: str) -> Counter:
    """Bugs found after merge, by the PR whose review missed them."""
    return Counter(int(n) for n in _MISSED.findall(changelog))


def pr_row(number: int, comments: list[dict], missed: Counter | dict) -> dict:
    review = next((c["body"] for c in comments if ai_review.MARKER in (c.get("body") or "")), "")
    tokens = (ai_review.read_state(review) or {}).get("tokens") or {}
    held = not_held = 0
    for c in comments:
        if REPLY_MARKER in (c.get("body") or "") and c.get("author_association") in REPLY_AUTHORS:
            h, n = parse_reply(c["body"])
            held, not_held = held + len(h), not_held + len(n)
    answered = held + not_held
    return {
        "pr": number,
        "reviews": tokens.get("reviews"), "read": tokens.get("read"), "written": tokens.get("written"),
        "held": held, "not_held": not_held, "held_share": held / answered if answered else None,
        "missed": missed.get(number, 0),
    }


def _cell(value: object) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.0%}"
    if isinstance(value, int) and value >= 10_000:
        return f"{value / 1000:,.0f}K"
    return str(value)


def table(rows: list[dict]) -> str:
    head = "| PR | reviews | tokens read | tokens written | held | didn't hold | held share | missed later |"
    lines = [head, "|" + "---|" * 8]
    for number, before in BEFORE.items():
        share = before["held"] / (before["held"] + before["not_held"])
        lines.append(f"| #{number} (before) | {before['reviews']} | {_cell(before['read'])} | "
                     f"{_cell(before['written'])} | {before['held']} | {before['not_held']} | {share:.0%} | – |")
    for r in rows:
        lines.append(f"| #{r['pr']} | {_cell(r['reviews'])} | {_cell(r['read'])} | {_cell(r['written'])} | "
                     f"{r['held']} | {r['not_held']} | {_cell(r['held_share'])} | {r['missed']} |")
    return "\n".join(lines)


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def _comments(repo: str, number: int) -> list[dict]:
    out = _gh("api", f"repos/{repo}/issues/{number}/comments", "--paginate", "--jq", ".[]")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("numbers", type=int, nargs="*")
    parser.add_argument("--since", type=int, help="every merged PR after this one")
    parser.add_argument("--repo", default="xuanbai01/Market-Analysis-Agent")
    args = parser.parse_args()
    numbers = list(args.numbers)
    if args.since is not None:
        merged = json.loads(_gh("pr", "list", "--repo", args.repo, "--state", "merged", "--limit", "200",
                                "--json", "number"))
        numbers += sorted(p["number"] for p in merged if p["number"] > args.since)
    missed = missed_by(Path("docs/changelog.md").read_text(encoding="utf-8"))
    print(table([pr_row(n, _comments(args.repo, n), missed) for n in sorted(set(numbers))]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
