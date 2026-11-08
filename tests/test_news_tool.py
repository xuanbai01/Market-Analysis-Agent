"""
Tests for ``app.services.news.fetch_news`` — the Phase 4.4.A
orchestrator-tool wrapper around ``news_repository.list_news`` +
``news_categorizer``.

The orchestrator's tools take only ``(symbol)`` so ``fetch_news``
opens its own AsyncSession internally. We patch ``list_news`` and
``categorize_news_headlines`` at the module boundary so neither the
DB nor the LLM is touched in unit tests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.schemas.news import NewsItemOut
from app.schemas.research import Claim


@pytest.fixture(autouse=True)
def _no_live_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """``fetch_news`` ingests the symbol's latest headlines before reading.
    Stub that step so no test reaches Yahoo, NewsAPI or Postgres; the
    ingest tests at the bottom replace this stub with their own."""
    from app.services import news as news_module

    async def _ingest(_session: Any, _symbol: str) -> int:
        return 0

    monkeypatch.setattr(news_module, "fetch_news_for_symbol", _ingest, raising=False)


def _news_item(
    *,
    nid: str = "abc123",
    title: str = "Apple beats Q1 estimates",
    url: str = "https://example.com/aapl-q1",
    source: str = "newsapi",
    ts_offset_hours: int = 1,
) -> NewsItemOut:
    return NewsItemOut(
        id=nid,
        ts=(datetime.now(UTC) - timedelta(hours=ts_offset_hours)).isoformat(),
        title=title,
        url=url,
        source=source,
        symbols=["AAPL"],
    )


async def test_returns_empty_dict_when_no_news_in_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No news for the symbol → empty result. The categorizer is not
    invoked (cost discipline mirrors its own short-circuit)."""
    from app.services import news as news_module

    async def _fake_list_news(
        _session: Any, symbol: str, hours: int, limit: int, cursor: Any
    ) -> tuple[list[NewsItemOut], None]:
        del symbol, hours, limit, cursor
        return [], None

    cat_calls = {"count": 0}

    async def _fake_categorize(headlines: list[str]) -> dict[int, dict[str, str]]:
        del headlines
        cat_calls["count"] += 1
        return {}

    monkeypatch.setattr(news_module, "list_news", _fake_list_news)
    monkeypatch.setattr(
        news_module, "categorize_news_headlines", _fake_categorize
    )

    result = await news_module.fetch_news("AAPL")

    assert result == {}
    assert cat_calls["count"] == 0


async def test_returns_one_claim_per_article_with_sentiment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each NewsItemOut becomes one Claim. Description = title; value =
    sentiment string from the categorizer; source.url = article URL;
    source.detail encodes the category."""
    from app.services import news as news_module

    items = [
        _news_item(nid="a", title="Apple beats Q1", url="https://x.com/1"),
        _news_item(nid="b", title="iPhone 17 launches", url="https://x.com/2"),
    ]

    async def _fake_list_news(*_a: Any, **_kw: Any) -> tuple[list[NewsItemOut], None]:
        return items, None

    async def _fake_categorize(headlines: list[str]) -> dict[int, dict[str, str]]:
        del headlines
        return {
            0: {"category": "earnings", "sentiment": "positive"},
            1: {"category": "product", "sentiment": "neutral"},
        }

    monkeypatch.setattr(news_module, "list_news", _fake_list_news)
    monkeypatch.setattr(
        news_module, "categorize_news_headlines", _fake_categorize
    )

    result = await news_module.fetch_news("AAPL")

    assert len(result) == 2
    titles = {c.description for c in result.values()}
    assert titles == {"Apple beats Q1", "iPhone 17 launches"}

    earnings = next(
        c for c in result.values() if c.description == "Apple beats Q1"
    )
    assert isinstance(earnings, Claim)
    assert earnings.value == "positive"
    assert earnings.source.url == "https://x.com/1"
    assert earnings.source.detail is not None
    assert "category=earnings" in earnings.source.detail


async def test_falls_back_to_neutral_other_when_categorizer_misses_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the categorizer drops an index (Haiku malformed response),
    the article still ships as a Claim — category=other, sentiment=
    neutral — so the frontend can render it."""
    from app.services import news as news_module

    items = [
        _news_item(nid="a", title="One"),
        _news_item(nid="b", title="Two"),
    ]

    async def _fake_list_news(*_a: Any, **_kw: Any) -> tuple[list[NewsItemOut], None]:
        return items, None

    async def _fake_categorize(headlines: list[str]) -> dict[int, dict[str, str]]:
        del headlines
        return {0: {"category": "earnings", "sentiment": "positive"}}
        # Index 1 missing intentionally.

    monkeypatch.setattr(news_module, "list_news", _fake_list_news)
    monkeypatch.setattr(
        news_module, "categorize_news_headlines", _fake_categorize
    )

    result = await news_module.fetch_news("AAPL")

    assert len(result) == 2
    fallback = next(c for c in result.values() if c.description == "Two")
    assert fallback.value == "neutral"
    assert "category=other" in (fallback.source.detail or "")


async def test_uppercases_symbol_before_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``fetch_news("aapl")`` queries with ``"AAPL"`` to match the news
    tagger's storage convention."""
    from app.services import news as news_module

    seen: dict[str, str] = {}

    async def _fake_list_news(
        _session: Any, symbol: str, hours: int, limit: int, cursor: Any
    ) -> tuple[list[NewsItemOut], None]:
        del hours, limit, cursor
        seen["symbol"] = symbol
        return [], None

    async def _fake_categorize(_headlines: list[str]) -> dict:
        return {}

    monkeypatch.setattr(news_module, "list_news", _fake_list_news)
    monkeypatch.setattr(
        news_module, "categorize_news_headlines", _fake_categorize
    )

    await news_module.fetch_news("aapl")

    assert seen["symbol"] == "AAPL"


# ── Fresh headlines per report (2026-11, Phase 4.8 plan item 2) ──────
#
# Nothing wrote news_items on its own — the only writer was a manual
# POST /v1/news/ingest — so the News card stayed empty in production.
# fetch_news now ingests the symbol's latest headlines first, and any
# ingest failure or stall degrades to reading whatever the DB has.


def _patch_reads(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, str]]) -> None:
    from app.services import news as news_module

    async def _fake_list_news(_session: Any, symbol: str, **_kw: Any) -> tuple[list, None]:
        calls.append(("list", symbol))
        return [_news_item()], None

    async def _fake_categorize(headlines: list[str]) -> dict[int, dict[str, str]]:
        return {i: {"category": "earnings", "sentiment": "positive"} for i in range(len(headlines))}

    monkeypatch.setattr(news_module, "list_news", _fake_list_news)
    monkeypatch.setattr(news_module, "categorize_news_headlines", _fake_categorize)


async def test_ingests_latest_headlines_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import news as news_module

    calls: list[tuple[str, str]] = []

    async def _ingest(_session: Any, symbol: str) -> int:
        calls.append(("ingest", symbol))
        return 3

    monkeypatch.setattr(news_module, "fetch_news_for_symbol", _ingest)
    _patch_reads(monkeypatch, calls)

    result = await news_module.fetch_news("aapl")

    assert calls == [("ingest", "AAPL"), ("list", "AAPL")]
    assert len(result) == 1


async def test_ingest_failure_still_returns_stored_news(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services import news as news_module

    async def _ingest(_session: Any, _symbol: str) -> int:
        raise RuntimeError("yahoo rss down")

    monkeypatch.setattr(news_module, "fetch_news_for_symbol", _ingest)
    calls: list[tuple[str, str]] = []
    _patch_reads(monkeypatch, calls)

    with caplog.at_level(logging.INFO, logger="app.external"):
        result = await news_module.fetch_news("AAPL")

    assert len(result) == 1
    record = next(r for r in caplog.records if r.service_id == "research.news_query")
    assert record.outcome == "ok"
    assert record.output_summary["ingest_error"] == "RuntimeError"
    assert record.output_summary["item_count"] == 1


async def test_stalled_ingest_is_abandoned_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feedparser fetches with no timeout of its own; a hung feed must
    not hold the whole research report hostage."""
    from app.services import news as news_module

    async def _ingest(_session: Any, _symbol: str) -> int:
        await asyncio.sleep(30)
        return 0

    monkeypatch.setattr(news_module, "fetch_news_for_symbol", _ingest)
    monkeypatch.setattr(news_module, "_INGEST_TIMEOUT_SECONDS", 0.05)
    calls: list[tuple[str, str]] = []
    _patch_reads(monkeypatch, calls)

    started = time.perf_counter()
    result = await news_module.fetch_news("AAPL")

    assert time.perf_counter() - started < 5
    assert len(result) == 1


async def test_ingest_count_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services import news as news_module

    async def _ingest(_session: Any, _symbol: str) -> int:
        return 7

    monkeypatch.setattr(news_module, "fetch_news_for_symbol", _ingest)
    calls: list[tuple[str, str]] = []
    _patch_reads(monkeypatch, calls)

    with caplog.at_level(logging.INFO, logger="app.external"):
        await news_module.fetch_news("AAPL")

    record = next(r for r in caplog.records if r.service_id == "research.news_query")
    assert record.output_summary["ingested"] == 7
