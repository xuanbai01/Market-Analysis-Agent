"""
How the AI review splits a pull request into parts (scripts/ai_review.py).

One review of a whole feature PR (30-55K tokens of diff) found about 3
real problems a round, round after round, until its cap of findings
and its attention had paged through the PR (#128-#131: 41 rounds, 99
fixes). So each source file is read beside its own tests, in parts
small enough to be read with care, and the parts are reviewed at once.
Prose docs are left out by name: they are a quarter of a PR's diff and
yielded almost no findings.

Standard library only, like the script.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

GENERATED_PATTERNS = (
    "uv.lock", "*/uv.lock", "package-lock.json", "*/package-lock.json", "*.snap",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.ico", "*.pdf", "*.woff", "*.woff2",
)
# Markdown that holds rules a change can break; other Markdown is prose.
RULE_DOCS = ("CLAUDE.md", "docs/security.md", "docs/adr/*.md")
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx")

_DIFF_HEADER = re.compile(r"^diff --git a/.* b/(.*)$", re.M)


@dataclass(frozen=True)
class FileDiff:
    path: str
    text: str


@dataclass
class Plan:
    parts: list[list[FileDiff]] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    over_budget: list[str] = field(default_factory=list)


def split_diff(diff: str) -> list[FileDiff]:
    """One entry per file, in diff order; the path is the new path."""
    headers = list(_DIFF_HEADER.finditer(diff))
    files = []
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(diff)
        files.append(FileDiff(path=header.group(1), text=diff[header.start() : end]))
    return files


def is_generated(path: str) -> bool:
    """Lockfiles, snapshots and binaries: nothing a reviewer reads."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in GENERATED_PATTERNS)


def is_prose_doc(path: str) -> bool:
    if not path.endswith(".md"):
        return False
    return not any(fnmatch.fnmatch(path, pattern) for pattern in RULE_DOCS)


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") or ".test." in name or name.startswith("test_")


def wants_function_context(path: str) -> bool:
    """Source code is shown whole function by whole function, so the
    review sees what a hunk sits in. Tests keep three lines: whole test
    functions would double them for little."""
    return path.endswith(CODE_SUFFIXES) and not is_test(path)


def _source_key(path: str) -> str:
    """What a test file and its source file have in common."""
    name = path.rsplit("/", 1)[-1]
    if path.endswith(".py"):
        stem = name[:-3]
        return stem[len("test_"):] if stem.startswith("test_") else stem
    # Foo.test.tsx beside Foo.tsx; journal-text.test.ts beside journal-text.ts.
    return path.replace(".test.", ".")


def review_units(files: list[FileDiff]) -> list[list[FileDiff]]:
    """Each source file followed by its tests; the rest alone. In path
    order, so neighbouring files land in the same part."""
    sources = sorted((f for f in files if not is_test(f.path)), key=lambda f: f.path)
    tests = sorted((f for f in files if is_test(f.path)), key=lambda f: f.path)
    units: dict[str, list[FileDiff]] = {f.path: [f] for f in sources}
    by_key: dict[str, str] = {}
    for f in sources:
        by_key.setdefault(_source_key(f.path), f.path)
    for t in tests:
        home = by_key.get(_source_key(t.path))
        if home is not None:
            units[home].append(t)
        else:
            units[t.path] = [t]
    return [units[k] for k in sorted(units)]


def _size(files: list[FileDiff]) -> int:
    return sum(len(f.text) for f in files)


def _fill(units: list[list[FileDiff]], part_chars: int) -> list[list[FileDiff]]:
    parts: list[list[FileDiff]] = []
    current: list[FileDiff] = []
    for unit in units:
        # A unit too big for a part goes file by file; a file too big
        # for a part gets one of its own.
        pieces = [unit] if _size(unit) <= part_chars else [[f] for f in unit]
        for piece in pieces:
            if current and _size(current) + _size(piece) > part_chars:
                parts.append(current)
                current = []
            current = current + piece
    if current:
        parts.append(current)
    return parts


def pack(units: list[list[FileDiff]], part_chars: int, max_parts: int) -> tuple[list[list[FileDiff]], list[str]]:
    """Return (parts, paths left out). Over ``max_parts``, tests go
    first (a defect in the code matters more than one in its test), then
    the last parts."""
    parts = _fill(units, part_chars)
    if len(parts) <= max_parts:
        return parts, []
    over = [f.path for unit in units for f in unit if is_test(f.path)]
    parts = _fill([[f for f in unit if not is_test(f.path)] for unit in units], part_chars)
    parts = [p for p in parts if p]
    if len(parts) > max_parts:
        over += [f.path for p in parts[max_parts:] for f in p]
        parts = parts[:max_parts]
    return parts, over


def plan_parts(files: list[FileDiff], part_chars: int, max_parts: int) -> Plan:
    plan = Plan()
    plan.generated = [f.path for f in files if is_generated(f.path)]
    plan.docs = [f.path for f in files if not is_generated(f.path) and is_prose_doc(f.path)]
    left_out = set(plan.generated) | set(plan.docs)
    reviewed = [f for f in files if f.path not in left_out]
    plan.parts, plan.over_budget = pack(review_units(reviewed), part_chars, max_parts)
    return plan
