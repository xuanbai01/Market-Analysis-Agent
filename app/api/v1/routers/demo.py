"""
Public read-only demo routes. **Deliberately not behind the shared
secret** — see ``app/services/demo.py`` for what they can and cannot do,
and ``docs/security.md`` A01.

    GET /v1/demo                               tickers with a report to show
    GET /v1/demo/research/{symbol}             the latest stored report
    GET /v1/demo/market/{symbol}/prices        the stored prices

All three are GETs over stored data for the tickers in ``DEMO_SYMBOLS``.
A ticker off the list answers 404 whether or not anything is stored for
it, so the routes can't be used to probe what the owner has researched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session
from app.schemas.demo import DemoIndex
from app.schemas.market import MarketPricesOut
from app.schemas.research import ResearchReport
from app.services import demo
from app.services.market_prices import RANGE_TO_PERIOD

router = APIRouter()

_RANGE_PATTERN = "^(" + "|".join(RANGE_TO_PERIOD.keys()) + ")$"
_NOT_IN_DEMO = "Not part of the demo."


@router.get("/demo", response_model=DemoIndex)
async def demo_index(session: AsyncSession = Depends(get_session)) -> DemoIndex:
    """The demo tickers that have a report; empty when the demo is off."""
    return await demo.index(session)


@router.get("/demo/research/{symbol}", response_model=ResearchReport)
async def demo_research(symbol: str, session: AsyncSession = Depends(get_session)) -> ResearchReport:
    """The latest stored report for a demo ticker. Never generates one."""
    report = await demo.latest_report(session, symbol)
    if report is None:
        raise HTTPException(status_code=404, detail=_NOT_IN_DEMO)
    return report


@router.get("/demo/market/{symbol}/prices", response_model=MarketPricesOut)
async def demo_prices(
    symbol: str,
    range: str = Query("60D", pattern=_RANGE_PATTERN),
    session: AsyncSession = Depends(get_session),
) -> MarketPricesOut:
    """The stored daily closes for a demo ticker. Never fetches new ones."""
    prices = await demo.cached_prices(session, symbol, range)
    if prices is None:
        raise HTTPException(status_code=404, detail=_NOT_IN_DEMO)
    return prices
