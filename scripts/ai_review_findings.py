"""
What the AI review reads back and writes (scripts/ai_review.py): the
model's findings as JSON, the comment's Markdown, the state the comment
carries from one push to the next, and the author's replies.

Standard library only, like the script.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

SEVERITIES = ("high", "medium", "low")
MAX_FINDINGS_PER_PART = 8
# Two findings on one file within this many lines are one problem.
SAME_PLACE_LINES = 3
STATE_MAX_FINDINGS = 60
STATE_TEXT_CHARS = 300
REPLIES_MAX_CHARS = 6_000
REPLY_MARKER = "<!-- ai-review:reply -->"
# Replies are read only from people who can push: anyone else's comment
# would be a way to talk the review out of a finding.
REPLY_AUTHORS = ("OWNER", "MEMBER", "COLLABORATOR")

_STATE_OPEN = "<!-- ai-review-state "
_STATE_CLOSE = " -->"
_STATE = re.compile(r"<!-- ai-review-state (\{.*?\}) -->", re.S)


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    line: int | None
    defect: str
    failure: str
    passes: int = 1  # how many passes raised it


def _rank(f: Finding) -> tuple[int, str, int]:
    return SEVERITIES.index(f.severity), f.path, f.line or 0


def _json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("the answer holds no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the answer's JSON doesn't parse: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ValueError("the answer's JSON has no list of findings")
    return data


def _line(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    # isdecimal, not isdigit: "²" is a digit int() can't read.
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    return None


def _finding(item: object) -> Finding | None:
    """None for a finding without the parts that make it checkable: a
    finding with no failing input or state is the kind that didn't hold."""
    if not isinstance(item, dict):
        return None
    text = {k: str(item.get(k) or "").strip() for k in ("severity", "path", "defect", "failure")}
    severity = text["severity"].lower()
    if severity not in SEVERITIES or not (text["path"] and text["defect"] and text["failure"]):
        return None
    return Finding(severity, text["path"], _line(item.get("line")), text["defect"], text["failure"])


def parse(text: str) -> tuple[list[Finding], str, int]:
    """Return (findings most severe first, the riskiest part, how many were dropped).

    Raises ValueError when the answer isn't the JSON asked for."""
    data = _json_object(text)
    found = [f for f in (_finding(item) for item in data["findings"]) if f is not None]
    dropped = len(data["findings"]) - len(found)
    found.sort(key=_rank)
    if len(found) > MAX_FINDINGS_PER_PART:
        dropped += len(found) - MAX_FINDINGS_PER_PART
        found = found[:MAX_FINDINGS_PER_PART]
    return found, str(data.get("riskiest") or "").strip(), dropped


def _same_place(a: Finding, b: Finding) -> bool:
    if a.path != b.path:
        return False
    if a.line is None or b.line is None:
        return a.line is None and b.line is None and a.defect == b.defect
    return abs(a.line - b.line) <= SAME_PLACE_LINES


def merge_duplicates(found: list[Finding]) -> list[Finding]:
    """One finding per problem when several passes raised it: the most
    severe wording kept, with how many passes raised it."""
    merged: list[Finding] = []
    for f in sorted(found, key=_rank):
        twin = next((i for i, m in enumerate(merged) if _same_place(m, f)), None)
        if twin is None:
            merged.append(f)
        else:
            m = merged[twin]
            merged[twin] = Finding(m.severity, m.path, m.line, m.defect, m.failure, m.passes + f.passes)
    return merged


def _where(f: Finding) -> str:
    return f"`{f.path}:{f.line}`" if f.line is not None else f"`{f.path}`"


def render_findings(found: list[Finding]) -> str:
    if not found:
        return "Nothing worth raising."
    ordered = sorted(found, key=_rank)
    return "\n".join(
        f"{i}. **{f.severity}** · {_where(f)} — {f.defect} Fails when: {f.failure}"
        + (f" *(raised by {f.passes} passes)*" if f.passes > 1 else "")
        for i, f in enumerate(ordered, start=1)
    )


# ── state carried in the comment ─────────────────────────────────────


def embed_state(state: dict) -> str:
    # "--" inside a string would let "-->" close the hidden comment early;
    # JSON reads "-" back as "-".
    payload = json.dumps(state, separators=(",", ":")).replace("--", "-\\u002d")
    return f"{_STATE_OPEN}{payload}{_STATE_CLOSE}"


def read_state(body: str) -> dict | None:
    match = _STATE.search(body or "")
    if not match:
        return None
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def _short(f: Finding) -> dict:
    data = asdict(f)
    return {k: (v[:STATE_TEXT_CHARS] if isinstance(v, str) else v) for k, v in data.items()}


def merge_state_findings(earlier: list[dict], new: list[Finding]) -> list[dict]:
    """Every finding so far, oldest first, the newest kept when over the cap."""
    merged = list(earlier) + [_short(f) for f in new]
    return merged[-STATE_MAX_FINDINGS:]


def describe_earlier(earlier: list[dict]) -> str:
    lines = []
    for item in earlier:
        where = f"{item.get('path')}:{item.get('line')}" if item.get("line") else str(item.get("path"))
        lines.append(f"- {item.get('severity')} · {where} — {item.get('defect')}")
    return "\n".join(lines)


# ── the author's replies ─────────────────────────────────────────────


def replies_from(comments: list[dict]) -> str:
    """The author's answers to earlier findings, newest kept within the cap."""
    replies = [
        c["body"].replace(REPLY_MARKER, "").strip()
        for c in comments
        if REPLY_MARKER in (c.get("body") or "") and c.get("author_association") in REPLY_AUTHORS
    ]
    kept: list[str] = []
    used = 0
    for reply in reversed(replies):
        room = REPLIES_MAX_CHARS - used - 2
        if room <= 0:
            break
        # A reply's start says which finding it answers.
        piece = reply if len(reply) <= room else reply[:room]
        kept.append(piece)
        used += len(piece) + 2
    return "\n\n".join(reversed(kept))
