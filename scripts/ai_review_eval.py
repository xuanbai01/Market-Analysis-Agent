"""
Measure the AI review before changing how it runs (dev-only, not in CI's
review job).

Replays past PRs at the commit their first review saw and reviews each
four ways:
  A  the review on main: one pass over the whole diff, thinking low
  B  this branch's review in parts, with whole functions: one pass, thinking low
  C  the same, one pass, thinking off
  D  the same, FULL_PASSES passes with their lenses, thinking off (what CI runs)

Writes every finding and the tokens each way spent to a JSON file, for
grading by hand against what the later rounds found (docs/changelog.md).

"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_review  # noqa: E402
import ai_review_ask  # noqa: E402

_REVIEWED = re.compile(r"Reviewed ([0-9a-f]{7,40}) with")
_ITEM = re.compile(r"^\s*\d+\.\s+\*\*(high|medium|low)\*\*.*$", re.M | re.I)
_HISTORY = """query($n:Int!){repository(owner:"%s",name:"%s"){pullRequest(number:$n){
  title body mergeCommit{oid}
  comments(first:100){nodes{body userContentEdits(first:100){nodes{diff}}}}}}}"""


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def case(number: int, repo: str) -> dict:
    """The PR as its first review saw it: the commit, its base, the text."""
    owner, name = repo.split("/")
    data = json.loads(_run("gh", "api", "graphql", "-f", f"query={_HISTORY % (owner, name)}", "-F", f"n={number}"))
    pr = data["data"]["repository"]["pullRequest"]
    review = next(c for c in pr["comments"]["nodes"] if ai_review.MARKER in c["body"])
    versions = [e["diff"] or "" for e in review["userContentEdits"]["nodes"]] + [review["body"]]
    shas = [m.group(1) for v in versions if (m := _REVIEWED.search(v))]
    first = _oldest(shas)
    merge = pr["mergeCommit"]["oid"]
    base = _run("git", "merge-base", f"{merge}^1", first).strip()
    return {"number": number, "title": pr["title"], "body": pr["body"], "base": base, "head": first,
            "rounds": len(set(shas))}


def _oldest(shas: list[str]) -> str:
    """The first commit reviewed: the one the others descend from."""
    full = [_run("git", "rev-parse", s).strip() for s in dict.fromkeys(shas)]
    for candidate in full:
        if all(subprocess.run(["git", "merge-base", "--is-ancestor", candidate, other]).returncode == 0
               for other in full):
            return candidate
    return full[-1]


def _ask(key: str, model: str, base_url: str):
    return lambda messages, options: ai_review._ask_deepseek(messages, options, key=key, model=model,
                                                             base_url=base_url)


def _usage(u: ai_review_ask.Usage) -> dict:
    return {"read": u.read, "cached": u.cached, "written": u.written, "reasoning": u.reasoning, "calls": u.calls}


def run_main_review(c: dict, rules: str, ask) -> dict:
    """Config A: the review as it runs on main, loaded from main."""
    source = _run("git", "show", "origin/main:scripts/ai_review.py")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ai_review_main.py"
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("ai_review_main", path)
        old = importlib.util.module_from_spec(spec)
        sys.modules["ai_review_main"] = old
        spec.loader.exec_module(old)
    started = time.monotonic()
    files = old.split_diff(old._git_diff(c["base"], c["head"]))
    kept, _, over = old.select_files(files, old.MAX_DIFF_CHARS)
    messages = old.build_messages(c["title"], c["body"], "".join(f.text for f in kept), rules)
    text, response, thinking = old.request_review(lambda options: ask(messages, options))
    usage = ai_review_ask.Usage()
    usage.add(response.get("usage"))
    items = [m.group(0).strip() for m in _ITEM.finditer(text)]
    return {"findings": items, "text": text, "thinking": thinking, "usage": _usage(usage),
            "seconds": round(time.monotonic() - started), "parts": 1, "over_budget": over}


def run_parts(c: dict, rules: str, ask, thinking: bool, passes: int) -> dict:
    """Configs B, C and D: this branch's review, in parts."""
    rng = f"{c['base']}...{c['head']}"
    paths = ai_review._changed_paths(rng)
    outcome = ai_review_ask.review(files=ai_review.collect_files(rng, paths), all_paths=paths, title=c["title"],
                                   body=c["body"], rules=rules, ask=ask, part_chars=ai_review.PART_CHARS,
                                   max_parts=ai_review.MAX_PARTS, passes=passes, thinking=thinking)
    return {"findings": [f"{f.severity} · {f.path}:{f.line} — {f.defect} Fails when: {f.failure}"
                         + (f" (raised by {f.passes} passes)" if f.passes > 1 else "") for f in outcome.findings],
            "usage": _usage(outcome.usage), "seconds": round(outcome.seconds), "parts": len(outcome.plan.parts),
            "failed": outcome.failed, "docs": outcome.plan.docs, "over_budget": outcome.plan.over_budget}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("numbers", type=int, nargs="+")
    parser.add_argument("--out", default="review-eval.json")
    parser.add_argument("--configs", default="ABCD", help="which of A, B, C, D to run")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "xuanbai01/Market-Analysis-Agent"))
    args = parser.parse_args()
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("::error::DEEPSEEK_API_KEY is not set.")
        return 1
    ask = _ask(key, os.environ.get("AI_REVIEW_MODEL") or ai_review.DEFAULT_MODEL,
               os.environ.get("DEEPSEEK_BASE_URL") or ai_review.DEFAULT_BASE_URL)
    results = {}
    for number in args.numbers:
        c = case(number, args.repo)
        rules = ai_review.project_rules(ai_review._file_at(c["base"], "CLAUDE.md"))
        print(f"#{number}: first review at {c['head'][:7]} (of {c['rounds']} reviewed commits), base {c['base'][:7]}")
        with ThreadPoolExecutor(4) as pool:
            configs = {"A": (run_main_review, c, rules, ask),
                       "B": (run_parts, c, rules, ask, True, 1),
                       "C": (run_parts, c, rules, ask, False, 1),
                       "D": (run_parts, c, rules, ask, False, ai_review_ask.FULL_PASSES)}
            jobs = {name: pool.submit(*configs[name]) for name in args.configs if name in configs}
            runs = {}
            for name, job in jobs.items():
                try:
                    runs[name] = job.result()
                except Exception as exc:  # noqa: BLE001 - record the failure, keep the other configs
                    runs[name] = {"error": repr(exc)}
        for name, run in runs.items():
            print(f"  {name}: {len(run.get('findings', []))} findings, {run.get('parts')} parts, "
                  f"{run.get('seconds')} s, usage {run.get('usage')} {run.get('error', '')}")
        results[number] = {"case": {k: c[k] for k in ("base", "head", "rounds")}, "runs": runs}
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
