"""
Real-LLM golden-question tests. Skipped unless ``ANTHROPIC_API_KEY`` is
set so they don't burn cost on every push. Currently no cases — the
list grows as tools come online.

Run manually:

    ANTHROPIC_API_KEY=... uv run pytest tests/evals/test_golden.py -v

Once we have golden cases, this file will:
  1. Call the agent for each case.
  2. Grade the result via ``rubric.grade``.
  3. Assert factuality.score >= 0.95 and structure.valid.
  4. Report latency and unmatched numbers in the test output for
     post-mortem.
"""
from __future__ import annotations

import os

import pytest

from tests.evals.golden import GOLDEN_CASES


# Two reasons to skip golden evals:
#   - no ANTHROPIC_API_KEY → can't call the model at all
#   - no GOLDEN_CASES yet  → nothing to test
# Express both as a *single* placeholder test rather than parametrizing
# over an empty list (pytest's `parametrize([], ids=...)` call still
# evaluates the ids callback once and errors on the empty parameter).
if not GOLDEN_CASES:

    def test_golden_cases_pending() -> None:
        pytest.skip("No golden cases yet — populated as tools come online")

else:

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set; skipping live LLM eval suite",
    )
    @pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.symbol)
    async def test_golden_case(case) -> None:
        # Skeleton — fills in once the agent endpoint exists. Calls the
        # agent for `case.symbol`, grades the result, asserts factuality.
        pytest.skip("Agent endpoint not yet implemented (Phase 2.2)")
