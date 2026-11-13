"""
The public read-only demo (app/api/v1/routers/demo.py, 2026-11).

These are the only routes that answer without the shared secret and
return report data, so the tests are about the fence: only the tickers
the operator listed, only what is already stored, and never a call that
costs money or reaches a provider.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import dependencies as deps
from app.core import settings as settings_module
from app.db.models.candles import Candle
from app.db.models.research_reports import ResearchReportRow
from app.db.models.symbols import Symbol
from app.schemas.research import Claim, Confidence, ResearchReport, Section, Source
from app.services import demo

_SECRET = "the-secret"


def _report(symbol: str, generated_at: datetime, *, name: str | None = None) -> ResearchReport:
    src = Source(tool="test.tool", fetched_at=generated_at)
    return ResearchReport(
        symbol=symbol,
        name=name,
        generated_at=generated_at,
        sections=[
            Section(
                title="Valuation",
                claims=[Claim(description="Trailing P/E", value=28.5, source=src)],
                summary="Trades at 28.5x trailing earnings.",
                confidence=Confidence.HIGH,
            )
        ],
        overall_confidence=Confidence.HIGH,
    )


async def _store(db: AsyncSession, report: ResearchReport, *, focus: str = "full") -> None:
    db.add(
        ResearchReportRow(
            symbol=report.symbol,
            focus=focus,
            report_date=report.generated_at.date(),
            report_json=report.model_dump(mode="json"),
            generated_at=report.generated_at,
        )
    )
    await db.flush()


async def _seed_candles(db: AsyncSession, symbol: str, days: int) -> None:
    end = datetime.now(UTC)
    db.add(Symbol(symbol=symbol, name=f"{symbol} test"))
    await db.flush()
    db.add_all(
        Candle(
            symbol=symbol,
            ts=end - timedelta(days=days - 1 - i),
            interval="1d",
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("100") + Decimal(i),
            volume=1_000_000,
        )
        for i in range(days)
    )
    await db.flush()


@pytest.fixture(autouse=True)
def _demo_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """KO and NVDA are the demo tickers; the API is otherwise locked."""
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "ko, NVDA")
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", _SECRET)
    demo.clear_cache()
    deps.reset_demo_rate_limit_for_tests()


@pytest.fixture(autouse=True)
def _no_spending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any path to the LLM or a data provider fails the test."""
    from app.services import market_prices, research_orchestrator

    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the demo must never generate a report or call a provider")

    from app.services import llm

    monkeypatch.setattr(research_orchestrator, "compose_research_report", _boom)
    monkeypatch.setattr(market_prices, "ingest_market_data", _boom)
    monkeypatch.setattr(llm, "synth_call", _boom)
    monkeypatch.setattr(llm, "triage_call", _boom)


# ── Which tickers ────────────────────────────────────────────────────


def test_demo_symbols_are_parsed_uppercased_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", " ko,NVDA , ko,, brk-b ")
    assert demo.demo_symbols() == ("KO", "NVDA", "BRK-B")


def test_an_empty_setting_means_no_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "")
    assert demo.demo_symbols() == ()


def test_a_malformed_entry_is_dropped_not_served(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "KO,../etc,WAYTOOLONGTICKERNAME,A B")
    assert demo.demo_symbols() == ("KO",)


# ── Reports ──────────────────────────────────────────────────────────


async def test_a_demo_ticker_is_served_without_the_secret(client: AsyncClient, db_session: AsyncSession) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)))

    resp = await client.get("/v1/demo/research/KO")

    assert resp.status_code == 200
    assert resp.json()["symbol"] == "KO"


async def test_the_symbol_is_case_insensitive(client: AsyncClient, db_session: AsyncSession) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)))
    assert (await client.get("/v1/demo/research/ko")).status_code == 200


async def test_a_ticker_off_the_list_is_not_found_even_when_a_report_is_stored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _store(db_session, _report("AAPL", datetime.now(UTC)))

    resp = await client.get("/v1/demo/research/AAPL")

    assert resp.status_code == 404


async def test_a_demo_ticker_with_no_stored_report_is_not_found_and_nothing_is_generated(
    client: AsyncClient,
) -> None:
    # ``_no_spending`` would fail the test if this reached the orchestrator.
    assert (await client.get("/v1/demo/research/NVDA")).status_code == 404


async def test_the_latest_report_is_served_however_old(client: AsyncClient, db_session: AsyncSession) -> None:
    """The signed-in route rebuilds a report past its cache window. The
    demo cannot rebuild, so it shows what there is, with its date."""
    now = datetime.now(UTC)
    await _store(db_session, _report("KO", now - timedelta(days=90), name="older"))
    await _store(db_session, _report("KO", now - timedelta(days=40), name="newer"))

    body = (await client.get("/v1/demo/research/KO")).json()

    assert body["name"] == "newer"


async def test_only_full_reports_are_served(client: AsyncClient, db_session: AsyncSession) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)), focus="earnings")
    assert (await client.get("/v1/demo/research/KO")).status_code == 404


async def test_the_real_research_route_still_needs_the_secret(client: AsyncClient) -> None:
    assert (await client.post("/v1/research/KO")).status_code == 401
    assert (await client.get("/v1/research")).status_code == 401


# ── Index ────────────────────────────────────────────────────────────


async def test_the_index_lists_demo_tickers_that_have_a_report(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _store(db_session, _report("KO", datetime(2026, 11, 1, 12, tzinfo=UTC), name="The Coca-Cola Company"))
    await _store(db_session, _report("AAPL", datetime.now(UTC)))  # stored, not on the list

    resp = await client.get("/v1/demo")

    assert resp.status_code == 200
    assert resp.json() == {
        "symbols": [
            {"symbol": "KO", "name": "The Coca-Cola Company", "generated_at": "2026-11-01T12:00:00Z"}
        ]
    }


async def test_with_the_demo_off_everything_is_closed(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_SYMBOLS", "")
    await _store(db_session, _report("KO", datetime.now(UTC)))

    assert (await client.get("/v1/demo")).json() == {"symbols": []}
    assert (await client.get("/v1/demo/research/KO")).status_code == 404
    assert (await client.get("/v1/demo/market/KO/prices")).status_code == 404


# ── Prices ───────────────────────────────────────────────────────────


async def test_stored_prices_are_served_for_a_demo_ticker(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_candles(db_session, "KO", days=30)

    resp = await client.get("/v1/demo/market/KO/prices?range=60D")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "KO"
    assert len(body["prices"]) == 30
    assert body["latest"]["close"] == pytest.approx(129.0)


async def test_missing_prices_come_back_empty_instead_of_being_fetched(client: AsyncClient) -> None:
    """The signed-in route fetches from Yahoo on a miss; the demo doesn't."""
    resp = await client.get("/v1/demo/market/KO/prices?range=1Y")

    assert resp.status_code == 200
    assert resp.json()["prices"] == []


async def test_prices_for_a_ticker_off_the_list_are_not_found(client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_candles(db_session, "AAPL", days=30)
    assert (await client.get("/v1/demo/market/AAPL/prices")).status_code == 404


async def test_an_unknown_price_range_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/v1/demo/market/KO/prices?range=banana")).status_code == 422


# ── Repeat requests don't reach the database ─────────────────────────


async def test_a_repeated_request_is_answered_from_memory(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open route can be hit in a loop; it must not turn into a
    database query per request."""
    from app.services import research_cache

    await _store(db_session, _report("KO", datetime.now(UTC)))
    calls = 0
    real = research_cache.lookup_latest

    async def _counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return await real(*args, **kwargs)

    monkeypatch.setattr(research_cache, "lookup_latest", _counting)

    for _ in range(5):
        assert (await client.get("/v1/demo/research/KO")).status_code == 200
    assert calls == 1


# ── Under a flood (security review, 2026-11-13) ──────────────────────


async def test_a_repeated_request_does_not_rebuild_the_response(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report is a large document. Validating and serializing it again
    for every anonymous request would let a loop pin the one shared CPU,
    so the stored bytes are what gets sent."""
    await _store(db_session, _report("KO", datetime.now(UTC)))
    first = await client.get("/v1/demo/research/KO")

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a cached demo response was serialized again")

    monkeypatch.setattr(ResearchReport, "model_dump_json", _boom)
    monkeypatch.setattr(ResearchReport, "model_dump", _boom)

    again = await client.get("/v1/demo/research/KO")
    assert again.status_code == 200
    assert again.content == first.content


async def test_responses_tell_browsers_and_proxies_to_cache_them(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _store(db_session, _report("KO", datetime.now(UTC)))
    for path in ("/v1/demo", "/v1/demo/research/KO", "/v1/demo/market/KO/prices"):
        resp = await client.get(path)
        assert resp.headers["cache-control"] == "public, max-age=300", path
        assert resp.headers["content-type"].startswith("application/json"), path


async def test_one_caller_is_slowed_past_the_per_minute_limit(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_RATE_LIMIT_PER_MINUTE", 3)
    deps.reset_demo_rate_limit_for_tests()
    await _store(db_session, _report("KO", datetime.now(UTC)))

    statuses = [(await client.get("/v1/demo/research/KO")).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    limited = await client.get("/v1/demo")
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


async def test_the_limit_can_be_turned_off(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "DEMO_RATE_LIMIT_PER_MINUTE", 0)
    deps.reset_demo_rate_limit_for_tests()
    await _store(db_session, _report("KO", datetime.now(UTC)))
    assert {(await client.get("/v1/demo/research/KO")).status_code for _ in range(10)} == {200}


def test_a_source_url_that_is_not_a_web_address_is_dropped() -> None:
    """The dashboard renders ``Source.url`` as a link, and the demo makes
    report pages public. A ``javascript:`` address would run in the page
    that holds the owner's token; only http(s) survives."""
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from app.schemas.research import Source as _Source

    at = _datetime.now(_UTC)
    assert _Source(tool="t", fetched_at=at, url="https://www.sec.gov/x").url == "https://www.sec.gov/x"
    assert _Source(tool="t", fetched_at=at, url="HTTP://example.com/a").url == "HTTP://example.com/a"
    for bad in ("javascript:alert(1)", "data:text/html,x", " https://x.test", "ftp://x.test", ""):
        assert _Source(tool="t", fetched_at=at, url=bad).url is None, bad
    assert _Source(tool="t", fetched_at=at).url is None


async def test_an_unexpected_failure_does_not_describe_itself_to_the_caller(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 500 body used to carry ``str(exc)``: on an open route that can
    hand a stranger a SQL fragment or a hostname."""
    from httpx import ASGITransport
    from httpx import AsyncClient as _Client

    from app.api.v1.dependencies import get_session
    from app.main import app
    from app.services import research_cache

    async def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("connection to db.internal:5432 refused (password=hunter2)")

    monkeypatch.setattr(research_cache, "lookup_latest", _explode)

    async def _session() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = _session
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with _Client(transport=transport, base_url="http://test") as raw:
            resp = await raw.get("/v1/demo/research/KO")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 500
    assert "hunter2" not in resp.text and "db.internal" not in resp.text
    assert resp.json()["title"] == "Internal Server Error"
