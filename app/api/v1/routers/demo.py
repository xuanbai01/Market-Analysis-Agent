"""
Public read-only demo routes. **Deliberately not behind the shared
secret** — see ``app/services/demo.py`` for what they can and cannot do,
and ``docs/security.md`` A01.

    GET /v1/demo                               tickers with a report to show
    GET /v1/demo/research/{symbol}             the latest stored report
    GET /v1/demo/market/{symbol}/prices        the stored prices

All three are GETs over stored data for the tickers in ``DEMO_SYMBOLS``.
A ticker off the list answers 404 before anything is looked up, whether
or not a report is stored for it, so these routes say nothing about what
else has been researched. (Every other data route needs the secret;
``tests/test_route_auth.py`` pins the open set.)

Report and price bodies are sent as the bytes the service cached, not
re-serialized per request; ``response_model`` is there for the OpenAPI
docs only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import enforce_demo_rate_limit, get_session
from app.schemas.demo import DemoIndex
from app.schemas.market import MarketPricesOut
from app.schemas.research import ResearchReport
from app.services import demo
from app.services.market_prices import RANGE_TO_PERIOD

router = APIRouter(dependencies=[Depends(enforce_demo_rate_limit)])

_RANGE_PATTERN = "^(" + "|".join(RANGE_TO_PERIOD.keys()) + ")$"
_NOT_IN_DEMO = "Not part of the demo."
# Matches the service's in-memory TTL: a browser or proxy may reuse a
# response for as long as the server would have served the same bytes.
_CACHE_CONTROL = f"public, max-age={int(demo.CACHE_TTL_SECONDS)}"


def _json(body: bytes) -> Response:
    return Response(content=body, media_type="application/json", headers={"Cache-Control": _CACHE_CONTROL})


@router.get("/demo", response_model=DemoIndex)
async def demo_index(response: Response, session: AsyncSession = Depends(get_session)) -> DemoIndex:
    """The demo tickers that have a report; empty when the demo is off."""
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return await demo.index(session)


@router.get("/demo/research/{symbol}", response_model=ResearchReport)
async def demo_research(symbol: str, session: AsyncSession = Depends(get_session)) -> Response:
    """The latest stored report for a demo ticker. Never generates one."""
    report = await demo.stored_report(session, symbol)
    if report is None:
        raise HTTPException(status_code=404, detail=_NOT_IN_DEMO)
    return _json(report.body)


@router.get("/demo/market/{symbol}/prices", response_model=MarketPricesOut)
async def demo_prices(
    symbol: str,
    range: str = Query("60D", pattern=_RANGE_PATTERN),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The stored daily closes for a demo ticker. Never fetches new ones."""
    prices = await demo.stored_prices(session, symbol, range)
    if prices is None:
        raise HTTPException(status_code=404, detail=_NOT_IN_DEMO)
    return _json(prices)
