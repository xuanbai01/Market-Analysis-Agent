"""
Live cited reads of options reports (ADR 0008, PR5): the real LLM on
live Yahoo chains for a stock with a report coming, an index fund and a
quiet stock.

Code already drops any point quoting a number no fact shows, so what is
checked here is what code can't enforce: that enough survives to make a
read, and that it neither advises nor forecasts. Each read is printed
for a person to look over.

Run with the Live Eval workflow (suite "options") or
``uv run pytest -m live_llm tests/evals/test_options_read.py -s``.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services import llm, options_read, options_report

SYMBOLS = ("NVDA", "SPY", "KO")
MIN_POINTS = 3  # the prompt asks for 3 to 5
# Advice, valuation calls and forecasts the prompt forbids. Not "expected":
# "expected move" is one of the facts' own names.
_FORBIDDEN = re.compile(
    r"\b(buy|buying|sell|selling|should|recommend\w*|consider|cheap|expensive|rich|bargain|"
    r"overpriced|underpriced|will|likely)\b",
    re.IGNORECASE,
)


@pytest.mark.live_llm
@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.skipif(
    not llm.provider_api_key_configured(),
    reason=f"API key for LLM_PROVIDER={settings.LLM_PROVIDER} not set; skipping the live options read",
)
@pytest.mark.parametrize("symbol", SYMBOLS)
async def test_a_live_options_read(symbol: str) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        report = await options_report.get_report(session, symbol, now=now)
    assert report.status == "ok", f"{symbol}: {report.status}"

    read = await options_read.write_read(report, now)
    assert read is not None, f"{symbol}: nothing survived the checks"
    print(f"\n{symbol}, quotes {read.quoted_at.isoformat()}: {read.headline}")
    for point in read.points:
        cited = [read.claims[ref.index].description for ref in point.claim_refs]
        print(f"  - [{point.title}] {point.text}\n      cites: {cited}")

    assert len(read.points) >= MIN_POINTS, f"{symbol}: only {len(read.points)} point(s) survived"
    for text in (read.headline, *(p.text for p in read.points)):
        found = _FORBIDDEN.search(text)
        assert found is None, f"{symbol}: '{found.group(0)}' in: {text}"
