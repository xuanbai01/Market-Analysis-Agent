"""
Which routes the shared secret protects.

Phase 3.0 mounted ``require_shared_secret`` on ``/v1/research/*`` only,
which left anything that writes to the database or spends upstream
quota open to whoever finds the Fly hostname — even once
``BACKEND_SHARED_SECRET`` is set:

- ``GET /v1/market/{symbol}/prices`` falls through to a yfinance ingest
  + candle upsert on cache miss (and was documented as auth-gated);
- ``POST /v1/market/ingest`` runs a yfinance ingest;
- ``POST /v1/news/ingest`` spends the 100/day NewsAPI quota;
- ``POST /v1/symbols`` inserts rows.

The frontend already sends ``Authorization: Bearer <token>`` on every
call (``frontend/src/lib/api.ts``), so gating these breaks nothing.
Plain database reads (``GET /v1/news``, ``GET /v1/symbols``, market
snapshot/history, health) stay open.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.v1.dependencies import get_session
from app.api.v1.routers import lens as lens_router
from app.api.v1.routers import market as market_router
from app.api.v1.routers import news as news_router
from app.core import settings as settings_module
from app.core.auth import require_shared_secret
from app.main import app
from app.schemas.lens import LensReport
from app.schemas.market_overview import MarketOverview

_SECRET = "the-secret"

# (method, path, json body) for every route that writes or spends quota.
_GATED_CALLS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/v1/market/AAPL/prices?range=60D", None),
    ("GET", "/v1/market/overview", None),
    ("GET", "/v1/lens", None),
    ("GET", "/v1/lens/megacap-capex", None),
    ("POST", "/v1/market/ingest", {"symbol": "AAPL"}),
    ("POST", "/v1/news/ingest", {"symbol": "AAPL"}),
    ("POST", "/v1/news/ingest", None),
    ("POST", "/v1/symbols", {"symbol": "AAPL", "name": "Apple Inc."}),
]

# Write-method routes deliberately left ungated, each with its reason.
# None today: the last entry was a 501 stub, removed 2026-11.
_UNGATED_WRITE_PATHS: set[str] = set()


class _FakeSession:
    """Just enough AsyncSession for ``POST /v1/symbols``."""

    def add(self, _obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """Routes reach stubbed services only: no DB, no network."""

    async def _session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    async def _prices(_session: Any, symbol: str, range_: str) -> dict[str, Any]:
        bar = {"ts": "2026-11-06T05:00:00+00:00", "close": 342.37}
        return {
            "ticker": symbol,
            "range": range_,
            "prices": [{**bar, "volume": 44_676_300.0}],
            "latest": {**bar, "delta_abs": 1.2, "delta_pct": 0.35},
        }

    async def _ingest(*_a: Any, **_kw: Any) -> int:
        return 0

    async def _overview() -> MarketOverview:
        return MarketOverview(quotes=[], sentiment=None, generated_at=datetime.now(UTC))

    async def _lens(lens_id: str) -> LensReport:
        return LensReport(
            id=lens_id, title="t", description="d", tickers=[], method="m", years=[],
            companies=[], stats=[], facts=[], narrative=None, generated_at=datetime.now(UTC),
        )

    app.dependency_overrides[get_session] = _session
    monkeypatch.setattr(market_router, "get_prices_with_cache", _prices)
    monkeypatch.setattr(market_router, "ingest_market_data", _ingest)
    monkeypatch.setattr(market_router, "get_market_overview", _overview)
    monkeypatch.setattr(lens_router, "get_lens", _lens)
    monkeypatch.setattr(news_router, "fetch_news_for_symbol", _ingest)
    monkeypatch.setattr(news_router, "ingest_news_once", _ingest)
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", _SECRET)
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)


def _ids() -> list[str]:
    return [f"{m} {p.split('?')[0]}{' (no body)' if b is None else ''}" for m, p, b in _GATED_CALLS]


@pytest.mark.parametrize(("method", "path", "body"), _GATED_CALLS, ids=_ids())
async def test_gated_route_rejects_missing_token(
    client: AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    resp = await client.request(method, path, json=body)
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize(("method", "path", "body"), _GATED_CALLS, ids=_ids())
async def test_gated_route_rejects_wrong_token(
    client: AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    resp = await client.request(
        method, path, json=body, headers={"Authorization": "Bearer not-it"}
    )
    assert resp.status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), _GATED_CALLS, ids=_ids())
async def test_gated_route_accepts_correct_token(
    client: AsyncClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    resp = await client.request(
        method, path, json=body, headers={"Authorization": f"Bearer {_SECRET}"}
    )
    assert resp.status_code in (200, 201), resp.text


@pytest.mark.parametrize(("method", "path", "body"), _GATED_CALLS, ids=_ids())
async def test_gated_route_is_open_when_no_secret_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    """Local dev and the rest of the suite run with an empty secret."""
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    resp = await client.request(method, path, json=body)
    assert resp.status_code in (200, 201), resp.text


def _requires_secret(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is require_shared_secret:
            return True
        stack.extend(dep.dependencies)
    return False


def test_every_write_route_requires_the_shared_secret() -> None:
    """A new POST/PUT/PATCH/DELETE route must opt into the gate, or be
    added to ``_UNGATED_WRITE_PATHS`` with a reason."""
    ungated = sorted(
        f"{sorted(r.methods)} {r.path}"
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.methods & {"POST", "PUT", "PATCH", "DELETE"}
        and r.path not in _UNGATED_WRITE_PATHS
        and not _requires_secret(r)
    )
    assert ungated == []


def test_prices_route_requires_the_shared_secret() -> None:
    """GET, but it writes candles and calls yfinance on a cache miss."""
    route = next(
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path == "/v1/market/{symbol}/prices"
    )
    assert _requires_secret(route)


# The public read-only demo (app/services/demo.py): the only routes that
# return report data without the secret. Adding a fourth, or a write
# method, must be a decision, so the set is pinned here.
_OPEN_DEMO_PATHS = {
    "/v1/demo",
    "/v1/demo/research/{symbol}",
    "/v1/demo/market/{symbol}/prices",
}


def test_the_demo_routes_are_open_read_only_and_exactly_these() -> None:
    demo_routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/v1/demo")]
    assert {r.path for r in demo_routes} == _OPEN_DEMO_PATHS
    for route in demo_routes:
        assert route.methods == {"GET"}, route.path
        assert not _requires_secret(route), route.path


def test_every_other_report_and_price_route_still_requires_the_secret() -> None:
    gated_prefixes = ("/v1/research", "/v1/lens", "/v1/market/overview", "/v1/market/{symbol}/prices")
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith(gated_prefixes):
            assert _requires_secret(route), route.path
