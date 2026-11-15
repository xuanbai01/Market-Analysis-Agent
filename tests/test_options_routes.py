"""GET /v1/options/{symbol} and /chain/{expiry} (ADR 0008), service stubbed."""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1 import dependencies as deps
from app.api.v1.dependencies import get_session
from app.api.v1.routers import options as options_router
from app.core import settings as settings_module
from app.main import app
from app.schemas.options import ExpiryChain, IvHistory, OptionsReport
from app.services.options_chain import SymbolNotFound
from app.services.options_report import ExpiryNotListed, NoUsableQuotes

NOW = datetime(2026, 11, 14, 17, tzinfo=UTC)


def _report(symbol: str) -> OptionsReport:
    return OptionsReport(
        symbol=symbol, status="no_options", spot=None, quoted_at=NOW, at_close=True, rate=0.04, rate_assumed=False,
        iv30=None, iv30_extrapolated=False, iv90=None, skew25=None, rv20=None, rv60=None,
        put_call_open_interest=None, put_call_volume=None, expiries=[], listed_expiries=[], chain=None,
        earnings=None, history=IvHistory(points=[], sessions=0, since=None, percentile=None, rank=None),
        claims=[], generated_at=NOW,
    )


class _Service:
    def __init__(self) -> None:
        self.symbols: list[str] = []
        self.fail: Exception | None = None
        self.fresh: set[str] = set()

    async def get_report(self, _session: Any, symbol: str) -> OptionsReport:
        self.symbols.append(symbol)
        if self.fail:
            raise self.fail
        return _report(symbol)

    async def get_chain(self, _session: Any, symbol: str, expiry: date) -> ExpiryChain:
        if self.fail:
            raise self.fail
        return ExpiryChain(expiry=expiry, days=30.0, forward=100.0, atm_iv=0.25, smile=[], rows=[], open_interest=[])

    def is_fresh(self, symbol: str) -> bool:
        return symbol in self.fresh

    def has_chain(self, symbol: str, expiry: date) -> bool:
        return symbol in self.fresh and expiry in self.chains

    chains: set[date] = set()


@pytest_asyncio.fixture
async def setup(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[AsyncClient, _Service]]:
    service = _Service()

    async def _session() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_session] = _session
    monkeypatch.setattr(options_router, "get_report", service.get_report)
    monkeypatch.setattr(options_router, "get_chain", service.get_chain)
    monkeypatch.setattr(options_router, "is_fresh", service.is_fresh)
    monkeypatch.setattr(options_router, "has_chain", service.has_chain)
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    monkeypatch.setattr(settings_module.settings, "OPTIONS_RATE_LIMIT_PER_HOUR", 2)
    deps.reset_options_rate_limit_for_tests()
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, service
    finally:
        app.dependency_overrides.pop(get_session, None)
        deps.reset_options_rate_limit_for_tests()


async def test_the_report_upper_cases_the_symbol(setup: Any) -> None:
    client, service = setup
    response = await client.get("/v1/options/nvda")
    assert response.status_code == 200
    assert response.json()["symbol"] == "NVDA" and service.symbols == ["NVDA"]


@pytest.mark.parametrize("path", ["/v1/options/..%2Fetc", "/v1/options/WAYTOOLONGSYM", "/v1/options/SPY/chain/2026-13-40"])
async def test_a_malformed_symbol_or_date_is_422(setup: Any, path: str) -> None:
    client, _service = setup
    assert (await client.get(path)).status_code in (404, 422)


async def test_bad_symbols_never_reach_the_service(setup: Any) -> None:
    client, service = setup
    await client.get("/v1/options/WAYTOOLONGSYM")
    await client.get("/v1/options/A B")
    assert service.symbols == []


@pytest.mark.parametrize(
    ("error", "status"),
    [(SymbolNotFound("ZZZZQ"), 404), (RuntimeError("yahoo down"), 503)],
)
async def test_report_errors(setup: Any, error: Exception, status: int) -> None:
    client, service = setup
    service.fail = error
    assert (await client.get("/v1/options/ZZZZQ")).status_code == status


@pytest.mark.parametrize(
    ("error", "status"),
    [(ExpiryNotListed(date(2027, 3, 19)), 404), (NoUsableQuotes(date(2027, 3, 19)), 404), (RuntimeError("x"), 503)],
)
async def test_chain_errors(setup: Any, error: Exception, status: int) -> None:
    client, service = setup
    service.fail = error
    assert (await client.get("/v1/options/SPY/chain/2027-03-19")).status_code == status


async def test_the_chain_route(setup: Any) -> None:
    client, _service = setup
    response = await client.get("/v1/options/spy/chain/2026-12-18")
    assert response.status_code == 200 and response.json()["expiry"] == "2026-12-18"


async def test_cache_misses_are_rate_limited_and_cached_reports_are_not(setup: Any) -> None:
    client, service = setup
    statuses = [(await client.get(f"/v1/options/T{i}")).status_code for i in range(3)]
    assert statuses == [200, 200, 429]
    service.fresh = {"T0"}
    assert (await client.get("/v1/options/T0")).status_code == 200


async def test_an_expiry_that_needs_a_fetch_counts_against_the_limit(setup: Any) -> None:
    """DeepSeek on PR 110: with the report cached, /chain fetched freely."""
    client, service = setup
    service.fresh = {"SPY"}
    statuses = [(await client.get(f"/v1/options/SPY/chain/2027-0{m}-19")).status_code for m in (1, 2, 3)]
    assert statuses == [200, 200, 429]
    service.chains = {date(2027, 1, 19)}
    assert (await client.get("/v1/options/SPY/chain/2027-01-19")).status_code == 200
