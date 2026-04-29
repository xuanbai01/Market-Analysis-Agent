"""
Programmatic confidence rules for research-report sections.

Confidence is set in code, never by the LLM. The agent's job is prose;
the contract with the caller about *how trustworthy this section is*
must not depend on a model's self-assessment. Two independent signals
drive the score:

1. **Density** — fraction of claims whose ``value`` is not None. A
   section made of mostly None claims is structurally sparse.
2. **Freshness** — age in days of the oldest ``Claim.source.fetched_at``
   in the section. A fully-populated section made of stale data caps at
   MEDIUM rather than HIGH.

| Density   | Freshness ≤ 30 days | Freshness > 30 days |
|-----------|---------------------|----------------------|
| < 50%     | LOW                 | LOW                  |
| 50%–80%   | MEDIUM              | MEDIUM               |
| ≥ 80%     | HIGH                | MEDIUM               |

Empty claim list → LOW (no data at all is the strongest "no signal").

Thresholds are placeholders documented in the v2.2 plan; tune by
re-scoring known-good golden cases as the eval harness fills in.

## Why these rules and not others

- **Density before freshness:** a sparse but fresh section is still
  unreliable, but a dense stale section is at least directionally
  correct. So density gates HIGH first.
- **Oldest claim wins:** a section composed from two tools where one
  pulled fresh data and the other returned a 90-day-cached entry is
  only as fresh as its oldest claim. This catches the case where one
  upstream provider was stale-but-cached.
- **Bool / int / empty-string count as non-null:** ``False``,
  ``0``, and ``""`` are all real values in this domain (``beat=False``,
  ``shares_bought=0``, ``ticker=""``-fallback). Density measures
  *presence*, not *truthiness*.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.research import Claim, Confidence

# Density thresholds (fraction non-null).
_HIGH_DENSITY_THRESHOLD = 0.80
_MEDIUM_DENSITY_THRESHOLD = 0.50

# Freshness threshold in days. ``HIGH`` requires every claim within
# this window from "now"; sections older than this cap at ``MEDIUM``.
_FRESHNESS_DAYS = 30


def score_section(claims: list[Claim]) -> Confidence:
    """Return the confidence band for a section's claim list.

    Pure function — no I/O, no LLM. ``now`` is read inside via
    ``datetime.now(UTC)``; tests that need deterministic age simulate
    by setting each claim's ``Source.fetched_at`` to a known offset.
    """
    if not claims:
        return Confidence.LOW

    non_null_count = sum(1 for c in claims if c.value is not None)
    density = non_null_count / len(claims)

    if density < _MEDIUM_DENSITY_THRESHOLD:
        return Confidence.LOW

    # Freshness: oldest claim age caps the section.
    now = datetime.now(UTC)
    max_age_days = max((now - c.source.fetched_at).days for c in claims)
    is_fresh = max_age_days <= _FRESHNESS_DAYS

    if density >= _HIGH_DENSITY_THRESHOLD and is_fresh:
        return Confidence.HIGH
    return Confidence.MEDIUM
