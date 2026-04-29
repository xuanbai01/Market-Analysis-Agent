"""
Real-LLM golden-question tests. Skipped unless ``ANTHROPIC_API_KEY``
is set so the cost burn is opt-in rather than charged on every push.

Run manually:

    ANTHROPIC_API_KEY=... uv run pytest tests/evals/test_golden.py -v

For each case:
  1. Call ``compose_research_report(symbol, focus)`` end-to-end.
     Real Anthropic API + real tool fan-out (yfinance, SEC EDGAR,
     FRED). Wall-clock ~10–30 seconds per case.
  2. Run the rubric scorers (structure + factuality + latency).
  3. Assert ``structure.valid`` and ``factuality.score >= 0.95``.
  4. Print latency + unmatched numbers for post-mortem on flaky cases.

The factuality threshold (0.95, not 1.0) is deliberate: the rubric is
a regex over prose and produces occasional false positives (a "2026
guidance" number, a confidence-interval footnote). Tighten when the
prompt and rubric are stable; for now, 5% slack absorbs noise without
hiding real hallucinations.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from app.core.settings import settings
from app.services.research_orchestrator import compose_research_report
from app.services.research_tool_registry import Focus
from tests.evals.golden import GOLDEN_CASES
from tests.evals.rubric import grade

# Two reasons to skip golden evals:
#   - no ANTHROPIC_API_KEY → can't call the model at all
#   - no GOLDEN_CASES yet  → nothing to test
# Express both as a *single* placeholder test rather than parametrizing
# over an empty list (pytest's ``parametrize([], ids=...)`` call still
# evaluates the ids callback once and errors on the empty parameter).
#
# The skipif checks ``settings.ANTHROPIC_API_KEY`` (the same source the
# LLM client reads) rather than ``os.environ`` directly — that way
# ``.env``-based config works without also exporting the env var to
# the shell.
if not GOLDEN_CASES:

    def test_golden_cases_pending() -> None:
        pytest.skip("No golden cases yet — populated as tools come online")

else:

    @pytest.mark.skipif(
        not settings.ANTHROPIC_API_KEY,
        reason="ANTHROPIC_API_KEY not set (in env or .env); "
               "skipping live LLM eval suite",
    )
    @pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: f"{c.symbol}-{c.focus}")
    async def test_golden_case(case) -> None:
        focus = Focus(case.focus)

        start = time.perf_counter()
        report = await compose_research_report(case.symbol, focus)
        elapsed_ms = (time.perf_counter() - start) * 1000

        result = grade(report, elapsed_ms)

        # Structural correctness: the report is a valid ResearchReport
        # by construction (it's a Pydantic model coming out of the
        # orchestrator), but `grade` runs the validation again as a
        # belt-and-suspenders check against schema drift.
        assert result.structure.valid, (
            f"{case.symbol}/{case.focus}: structure invalid — "
            f"{result.structure.errors}"
        )

        # Factuality: every decimal number in any section's summary
        # should appear in that section's claim values. <0.95 means
        # the model fabricated numbers — a real regression worth
        # failing the test loudly. Always print latency + section
        # summaries so factuality misses are diagnosable from the
        # test output alone (no need to re-run with a debugger).
        print(
            f"\n{case.symbol}/{case.focus}: "
            f"latency={elapsed_ms:.0f} ms, "
            f"sections={len(report.sections)}, "
            f"overall={report.overall_confidence.value}, "
            f"factuality={result.factuality.score:.3f}"
        )
        if result.factuality.score < 0.95:
            _dump_report_for_diagnosis(report, result.factuality.unmatched_numbers)

        assert result.factuality.score >= 0.95, (
            f"{case.symbol}/{case.focus}: factuality {result.factuality.score:.2f}, "
            f"unmatched numbers in prose: {result.factuality.unmatched_numbers}"
        )


def _dump_report_for_diagnosis(report: Any, unmatched: list[float]) -> None:
    """Print every section's summary + claim values when factuality fails.

    Lets a human read the prose alongside the available claim values and
    decide whether the model fabricated, paraphrased, or the rubric
    over-flagged. Prints to stdout so pytest with ``-s`` surfaces it.
    """
    unmatched_set = {round(n, 2) for n in unmatched}
    print("\n" + "=" * 72)
    print(f"  DIAGNOSTIC DUMP — {report.symbol} (factuality miss)")
    print("=" * 72)
    print(f"  Unmatched numbers: {sorted(unmatched_set)}")
    print()
    for section in report.sections:
        print(f"── {section.title}  [confidence={section.confidence.value}]")
        print(f"   Summary: {section.summary}")
        if section.claims:
            print(f"   Claims ({len(section.claims)}):")
            for c in section.claims:
                print(f"     - {c.description} = {c.value!r}")
        else:
            print("   Claims: (none)")
        print()
