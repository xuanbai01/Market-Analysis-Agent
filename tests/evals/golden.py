"""
Golden questions for the agent eval harness.

Each ``GoldenCase`` is a ``(symbol, expected_facts)`` pair where
``expected_facts`` is a list of (description, value, tolerance) triples
that the agent's report is expected to surface. Empty for now — gets
populated as tools come online and the agent has something to retrieve.

When adding a case:
  - Pick a symbol whose ground truth is unambiguous (large-cap, recent
    filer, low volatility on the metric in question).
  - Pin the *expected* values to the upstream data we can verify
    independently — yfinance.Ticker.info[trailingPE] on date X = Y.
  - Set tolerance reasonably wide. yfinance refreshes daily; a P/E of
    32.5 today might be 32.7 next week. The rubric is meant to catch
    *hallucinations* (P/E of 4.2 when reality is 32), not to chase
    upstream drift.

The case list is intentionally short to start. Quality > quantity:
five well-chosen golden questions catch most regressions; fifty
flaky ones train the team to ignore the harness.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExpectedFact:
    description: str
    value: float
    tolerance: float = 0.05  # 5% by default — see module docstring


@dataclass(frozen=True)
class GoldenCase:
    symbol: str
    focus: str = "full"
    facts: list[ExpectedFact] = field(default_factory=list)


# Empty until tools land. Each tool PR is expected to add 1–3 cases that
# exercise its outputs.
GOLDEN_CASES: list[GoldenCase] = []
