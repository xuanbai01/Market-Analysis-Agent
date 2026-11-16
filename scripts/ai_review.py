"""
AI review of a pull request by DeepSeek, posted as one PR comment.

Runs in CI (.github/workflows/ai-review.yml) on the standard library
only, so the job needs no install step. Claude writes most of this
repo's code; a model from another family reads the diff for what it
missed. It sees the diff, the PR's title and description, and the
project rules from the base commit's CLAUDE.md, not the rest of the
repo, so it can miss a break in a file the PR didn't touch.

How it reads a PR (#128-#131 took 41 whole-PR reviews and still found
about 3 real problems each, so one pass wasn't covering the PR):
- **In parts** (ai_review_shards): each source file beside its tests,
  about 50K characters a part, each with its own cap of findings. Prose
  docs are left out by name.
- **With context:** source files whole function by whole function.
- **Several passes, thinking off** (ai_review_ask): a full review reads
  each part three times at once, each pass looking hardest at different
  kinds of defect, and merges what they find. Measured, in the changelog.
- **Findings as JSON** (ai_review_findings), each with a failing input
  or state, or it's dropped.
- **Full, then incremental:** a full review when the PR opens, is
  reopened or marked ready, or gets the `ai-review-full` label. A later
  push reviews only what changed since the last review, shown the
  earlier findings and the author's replies (comments marked
  `<!-- ai-review:reply -->` by someone who can push).

One comment per PR, found again by MARKER and rewritten each time; it
carries the last reviewed commit and the findings so far.

Environment (all set by the workflow):
  DEEPSEEK_API_KEY   the repo secret
  GITHUB_TOKEN       the job's token, to post the comment
  GITHUB_REPOSITORY  owner/name
  GITHUB_EVENT_PATH  the pull_request event (action, label, number, title, body, SHAs)
  AI_REVIEW_MODEL    optional, default deepseek-flash
  AI_REVIEW_THINKING optional: "low" turns thinking on (off by default)
  DEEPSEEK_BASE_URL  optional, default https://api.deepseek.com
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ai_review_ask import (
    EARLIER_FULL_PROMPT,
    EARLIER_PROMPT,
    FIX_PASSES,
    FULL_PASSES,
    Usage,
    review,
)
from ai_review_findings import (
    Finding,
    describe_earlier,
    embed_state,
    merge_state_findings,
    read_state,
    render_findings,
    replies_from,
)
from ai_review_shards import FileDiff, Plan, plan_parts, split_diff, wants_function_context

MARKER = "<!-- ai-review:deepseek -->"
FULL_LABEL = "ai-review-full"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

# About 12K tokens of diff a part, at most 8 parts (tests are left out
# first past that, then the last parts).
PART_CHARS = 50_000
MAX_PARTS = 8
# The running totals the comment's state carries across a PR's reviews.
TOTAL_KEYS = ("reviews", "read", "cached", "written", "reasoning", "calls")
LLM_TIMEOUT_SECONDS = 300
GITHUB_TIMEOUT_SECONDS = 30
_PAGE_SIZE = 100

_RULES_START = "**Rules that came out of shipped work**"
_RULES_END = "**Deferred**"

def project_rules(claude_md: str) -> str:
    """The bullet list under "Rules that came out of shipped work"."""
    start = claude_md.find(_RULES_START)
    if start == -1:
        return ""
    body_start = claude_md.find("\n", start)
    end = claude_md.find(_RULES_END, body_start)
    section = claude_md[body_start : end if end != -1 else len(claude_md)]
    return section.strip()


def review_mode(action: str, label: str | None, state_sha: str | None, head_sha: str,
                is_ancestor: bool) -> str:
    """"full", "incremental" or "skip"."""
    if action == "labeled":
        return "full" if label == FULL_LABEL else "skip"
    if action in ("opened", "reopened", "ready_for_review"):
        return "full"
    if action != "synchronize":
        return "skip"
    if not state_sha:
        return "full"
    if state_sha == head_sha:
        return "skip"
    # A force-push leaves the old head out of the branch: review it all.
    return "incremental" if is_ancestor else "full"


def collect_files(rev_range: str, paths: list[str]) -> list[FileDiff]:
    """The diff of ``paths`` over ``rev_range``: source with whole
    functions, the rest with three lines. In ``paths`` order."""
    code = [p for p in paths if wants_function_context(p)]
    rest = [p for p in paths if not wants_function_context(p)]
    text = (_git_diff(rev_range, code, whole_functions=True) if code else "") + (
        _git_diff(rev_range, rest, whole_functions=False) if rest else "")
    by_path = {f.path: f for f in split_diff(text)}
    ordered = [by_path.pop(p) for p in paths if p in by_path]
    return ordered + list(by_path.values())


# ── what lands on the PR ─────────────────────────────────────────────


def _names(paths: list[str]) -> str:
    return ", ".join(f"`{p}`" for p in paths)


def _left_out(plan: Plan | None, failed: list[str]) -> str:
    reasons = []
    if failed:
        reasons.append(f"parts that failed: {_names(failed)}")
    if plan is not None:
        if plan.over_budget:
            reasons.append(f"over the size budget: {_names(plan.over_budget)}")
        if plan.docs:
            reasons.append(f"docs: {_names(plan.docs)}")
        if plan.generated:
            reasons.append(f"generated: {_names(plan.generated)}")
    return "; ".join(reasons)


def render_comment(*, findings: list[Finding], riskiest: list[str], head_sha: str, model: str, parts: int,
                   usage: Usage, plan: Plan | None, mode: str, earlier: list[dict], failed: list[str],
                   since: str | None = None, passes: int = 1, failed_passes: int = 0,
                   totals: dict | None = None) -> str:
    plural = "part" if parts == 1 else "parts"
    times = f", {passes} passes each" if passes > 1 else ""
    if mode == "incremental" and since:
        heading = f"Review of the changes since {since[:7]}, at {head_sha[:7]}, in {parts} {plural}{times}."
    else:
        heading = f"Full review of {head_sha[:7]} in {parts} {plural}{times}."
    # Lows fold away: with thinking off, about one in six held up when
    # graded (#128-#131), against two in five of the highs.
    main = [f for f in findings if f.severity != "low"]
    lows = [f for f in findings if f.severity == "low"]
    sections = [f"{MARKER}\n### AI review (DeepSeek)\n", heading,
                render_findings(main) if main or not lows else "Nothing above low."]
    if lows:
        # Numbered on from the others, so a reply's numbers are unique.
        sections.append(f"<details><summary>Lows ({len(lows)})</summary>\n\n"
                        f"{render_findings(lows, start=len(main) + 1)}\n\n</details>")
    if riskiest:
        sections.append("<details><summary>Riskiest, by part</summary>\n\n"
                        + "\n".join(f"- {r}" for r in riskiest) + "\n\n</details>")
    if earlier:
        sections.append(f"<details><summary>Earlier findings ({len(earlier)})</summary>\n\n"
                        + describe_earlier(earlier) + "\n\n</details>")
    footer = f"Reviewed {head_sha[:7]} with `{model}`: {usage.line()}. It sees the diff only, not the rest of the repo."
    left_out = _left_out(plan, failed)
    if left_out:
        footer += f" Not reviewed — {left_out}."
    if failed_passes:
        footer += (f" {failed_passes} of {parts * passes} passes failed; the other passes over"
                   " their parts stand.")
    so_far = add_totals(totals, usage)
    footer += (f" This PR so far: {so_far['reviews']} reviews, {so_far['read']:,} tokens read "
               f"({so_far['cached']:,} cached), {so_far['written']:,} written.")
    state = {"sha": head_sha, "findings": merge_state_findings(earlier, findings), "tokens": so_far}
    return "\n\n".join(sections) + f"\n\n---\n<sub>{footer}</sub>\n{embed_state(state)}\n"


def add_totals(totals: dict | None, usage: Usage) -> dict:
    """The PR's reviews so far, this one included: what ai_review_stats reads."""
    so_far = {k: (totals or {}).get(k) or 0 for k in TOTAL_KEYS}
    so_far["reviews"] += 1
    for k in TOTAL_KEYS[1:]:
        so_far[k] += getattr(usage, k)
    return so_far


def render_nothing_to_review(head_sha: str, plan: Plan, earlier: list[dict], totals: dict | None = None) -> str:
    why = _left_out(plan, []) or "the diff has no files"
    state = {"sha": head_sha, "findings": earlier}
    if totals:
        state["tokens"] = totals  # nothing was asked, so nothing to add
    # A docs-only push mustn't hide what the last review found.
    folded = (f"\n<details><summary>Earlier findings ({len(earlier)})</summary>\n\n"
              f"{describe_earlier(earlier)}\n\n</details>\n") if earlier else ""
    return (f"{MARKER}\n### AI review (DeepSeek)\n\nNothing to review at {head_sha[:7]}. "
            f"Left out — {why}.\n{folded}{embed_state(state)}\n")


def find_comment_id(comments: list[dict]) -> int | None:
    for comment in comments:
        if MARKER in (comment.get("body") or ""):
            return comment["id"]
    return None


# ── I/O: git, DeepSeek, GitHub ───────────────────────────────────────


def _request(url: str, *, token: str, method: str = "GET", payload: dict | None = None,
             timeout: int = GITHUB_TIMEOUT_SECONDS, extra_headers: dict | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _git(*args: str) -> subprocess.CompletedProcess:
    # quotepath off: git would otherwise quote a non-ASCII path
    # ("a/caf\303\251.md") and the header pattern would skip the file.
    return subprocess.run(["git", "-c", "core.quotepath=off", *args],
                          capture_output=True, text=True, encoding="utf-8")


def _changed_paths(rev_range: str) -> list[str]:
    result = _git("diff", "--name-only", "--no-color", rev_range)
    result.check_returncode()
    return [line for line in result.stdout.splitlines() if line]


def _git_diff(rev_range: str, paths: list[str], *, whole_functions: bool) -> str:
    context = "--function-context" if whole_functions else "-U3"
    result = _git("diff", "--no-color", "--no-ext-diff", context, rev_range, "--", *paths)
    result.check_returncode()
    return result.stdout


def _is_ancestor(old: str, new: str) -> bool:
    return _git("merge-base", "--is-ancestor", old, new).returncode == 0


def _file_at(sha: str, path: str) -> str:
    """``path`` as of commit ``sha``; empty when it doesn't exist there."""
    result = _git("show", f"{sha}:{path}")
    return result.stdout if result.returncode == 0 else ""


def _ask_deepseek(messages: list[dict[str, str]], options: dict, *, key: str, model: str,
                  base_url: str) -> dict:
    try:
        return _request(f"{base_url.rstrip('/')}/chat/completions", token=key, method="POST",
                        payload={"model": model, "messages": messages, **options},
                        timeout=LLM_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"DeepSeek returned HTTP {exc.code}: {detail}") from exc
    except http.client.HTTPException as exc:
        # A long thinking request can end with the connection cut mid-body
        # (IncompleteRead), which isn't an OSError.
        raise RuntimeError(f"DeepSeek's connection dropped: {exc!r}") from exc


_GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _list_comments(*, repo: str, number: int, token: str) -> list[dict]:
    api = f"https://api.github.com/repos/{repo}"
    comments: list[dict] = []
    page = 1
    while True:
        batch = _request(f"{api}/issues/{number}/comments?per_page={_PAGE_SIZE}&page={page}",
                         token=token, extra_headers=_GITHUB_HEADERS)
        comments += batch
        if len(batch) < _PAGE_SIZE:
            return comments
        page += 1


def _post_or_update(body: str, *, repo: str, number: int, token: str, existing: int | None) -> str:
    api = f"https://api.github.com/repos/{repo}"
    if existing is None:
        _request(f"{api}/issues/{number}/comments", token=token, method="POST",
                 payload={"body": body}, extra_headers=_GITHUB_HEADERS)
        return "posted"
    _request(f"{api}/issues/comments/{existing}", token=token, method="PATCH",
             payload={"body": body}, extra_headers=_GITHUB_HEADERS)
    return "updated"


def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        # A review job that quietly does nothing looks like a passing
        # review. Fail where it shows.
        print("::error::The DEEPSEEK_API_KEY repo secret is not set.")
        return 1

    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    action, label = event.get("action") or "opened", (event.get("label") or {}).get("name")
    if action == "labeled" and label != FULL_LABEL:
        print(f"Label {label!r} isn't {FULL_LABEL!r}: nothing to do.")
        return 0
    pr = event["pull_request"]
    model = os.environ.get("AI_REVIEW_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
    repo, number, token = os.environ["GITHUB_REPOSITORY"], pr["number"], os.environ["GITHUB_TOKEN"]
    base, head = pr["base"]["sha"], pr["head"]["sha"]

    comments = _list_comments(repo=repo, number=number, token=token)
    existing = find_comment_id(comments)
    previous = next((c["body"] for c in comments if c.get("id") == existing), "") if existing else ""
    state = read_state(previous) or {}
    state_sha = state.get("sha")
    ancestor = bool(state_sha) and state_sha != head and _is_ancestor(state_sha, head)
    mode = review_mode(action, label, state_sha, head, ancestor)
    if mode == "skip":
        print(f"Nothing to do on {action!r}: {head[:7]} was reviewed already.")
        return 0

    pr_paths = _changed_paths(f"{base}...{head}")
    if mode == "incremental":
        rev_range = f"{state_sha}..{head}"
        in_pr = set(pr_paths)
        paths = [p for p in _changed_paths(rev_range) if p in in_pr]
        earlier = list(state.get("findings") or [])
        earlier_text = EARLIER_PROMPT.format(sha=state_sha[:7], findings=describe_earlier(earlier) or "(none)",
                                             replies=replies_from(comments) or "(none)")
        changed: set[str] | None = set(paths)
    else:
        # A full review again (the label, or after a force-push) sees what
        # was raised and answered, so it doesn't raise the answered again.
        rev_range, paths, changed = f"{base}...{head}", pr_paths, None
        earlier = list(state.get("findings") or [])
        earlier_text = EARLIER_FULL_PROMPT.format(
            findings=describe_earlier(earlier), replies=replies_from(comments) or "(none)") if earlier else ""

    files = collect_files(rev_range, paths)
    post = dict(repo=repo, number=number, token=token, existing=existing)
    plan = plan_parts(files, PART_CHARS, MAX_PARTS)
    if not plan.parts:
        # Say so on the PR: no comment reads as a review that never ran,
        # and a review of code since removed would otherwise stand.
        action_taken = _post_or_update(render_nothing_to_review(head, plan, earlier, state.get("tokens")), **post)
        print(f"Nothing reviewable ({mode}). Comment {action_taken}.")
        return 0

    # The base commit's rules: a PR doesn't get to weaken what it is judged by.
    rules = project_rules(_file_at(base, "CLAUDE.md"))
    outcome = review(files=files, all_paths=pr_paths, title=pr["title"], body=pr.get("body"), rules=rules,
                     ask=lambda messages, options: _ask_deepseek(messages, options, key=key, model=model,
                                                                 base_url=base_url),
                     part_chars=PART_CHARS, max_parts=MAX_PARTS,
                     passes=FULL_PASSES if mode == "full" else FIX_PASSES,
                     thinking=(os.environ.get("AI_REVIEW_THINKING") or "").lower() == "low",
                     earlier=earlier_text, changed=changed)
    print(f"{mode.capitalize()} review: {len(outcome.findings)} findings in {len(outcome.plan.parts)} parts, "
          f"{outcome.seconds:.0f} s; {outcome.usage.line()}.")
    if len(outcome.failed) == sum(len(p) for p in outcome.plan.parts):
        print("::error::Every part of the review failed.")
        return 1

    body = render_comment(findings=outcome.findings, riskiest=outcome.riskiest, head_sha=head, model=model,
                          parts=len(outcome.plan.parts), usage=outcome.usage, plan=outcome.plan, mode=mode,
                          earlier=earlier, failed=outcome.failed, since=state_sha if mode == "incremental" else None,
                          passes=outcome.passes, failed_passes=outcome.failed_passes,
                          totals=state.get("tokens"))
    print(f"Review comment {_post_or_update(body, **post)}.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(body.replace(MARKER, "") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
