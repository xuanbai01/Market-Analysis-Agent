"""
Measure the AI review before changing how it runs (dev-only, not in CI's
review job).

Replays past PRs at the commit their first review saw and reviews each
three ways:
  A  the review on main: one pass over the whole diff, thinking low
  B  this branch's review: in parts, with whole functions, thinking low
  C  the same in parts, thinking off

Writes every finding and the tokens each way spent to a JSON file, for
grading by hand against what the later rounds found (docs/changelog.md).

Needs DEEPSEEK_API_KEY, and `gh` signed in (GH_TOKEN in Actions) to read
the PRs and their review comment's history. Run from the repo root:
  python scripts/ai_review_eval.py 128 129 130 131 --out review-eval.json

Live Eval runs it with suite "review" (.github/workflows/live-eval.yml).
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


def _usage(u: ai_review.Usage) -> dict:
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
    usage = ai_review.Usage()
    usage.add(response.get("usage"))
    items = [m.group(0).strip() for m in _ITEM.finditer(text)]
    return {"findings": items, "text": text, "thinking": thinking, "usage": _usage(usage),
            "seconds": round(time.monotonic() - started), "parts": 1, "over_budget": over}


def run_parts(c: dict, rules: str, ask, thinking: bool) -> dict:
    """Configs B and C: this branch's review, in parts."""
    rng = f"{c['base']}...{c['head']}"
    paths = ai_review._changed_paths(rng)
    outcome = ai_review.review(files=ai_review.collect_files(rng, paths), all_paths=paths, title=c["title"],
                               body=c["body"], rules=rules, ask=ask, thinking=thinking)
    return {"findings": [f"{f.severity} · {f.path}:{f.line} — {f.defect} Fails when: {f.failure}"
                         for f in outcome.findings],
            "usage": _usage(outcome.usage), "seconds": round(outcome.seconds), "parts": len(outcome.plan.parts),
            "failed": outcome.failed, "docs": outcome.plan.docs, "over_budget": outcome.plan.over_budget}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("numbers", type=int, nargs="+")
    parser.add_argument("--out", default="review-eval.json")
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
        with ThreadPoolExecutor(3) as pool:
            jobs = {"A": pool.submit(run_main_review, c, rules, ask),
                    "B": pool.submit(run_parts, c, rules, ask, True),
                    "C": pool.submit(run_parts, c, rules, ask, False)}
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
