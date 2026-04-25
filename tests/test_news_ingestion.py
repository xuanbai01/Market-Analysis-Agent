"""
Tests for the news ingestion service. Same pattern as
``test_data_ingestion.py``: mock the providers via the registry so
none of these actually call NewsAPI or Yahoo Finance — that would make
the suite slow, flaky, and dependent on external uptime.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news import NewsItemModel
from app.db.models.news_symbols import NewsSymbol
from app.db.models.symbols import Symbol
from app.services.news_ingestion import (
    PROVIDERS,
    _hash_id,
    fetch_news_for_symbol,
)

# ── Fixtures / helpers ───────────────────────────────────────────────


async def _seed_universe(session: AsyncSession) -> None:
    """Three symbols so we can exercise the tagger over a real universe."""
    session.add_all(
        [
            Symbol(symbol="NVDA", name="NVIDIA Corp"),
            Symbol(symbol="AMD", name="Advanced Micro Devices"),
            Symbol(symbol="AAPL", name="Apple Inc"),
        ]
    )
    await session.flush()


def _article(
    *,
    title: str,
    url: str,
    source: str = "fake",
    ts: datetime | None = None,
) -> dict:
    return {
        "ts": ts or datetime.now(UTC),
        "title": title,
        "url": url,
        "source": source,
    }


# ── Basic ingest path ────────────────────────────────────────────────


async def test_ingest_writes_articles_and_returns_count(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_universe(db_session)
    articles = [
        _article(title="NVDA earnings beat", url="https://ex.com/a"),
        _article(title="NVDA roadmap update", url="https://ex.com/b"),
    ]
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: articles)

    count = await fetch_news_for_symbol(
        db_session, "NVDA", providers=["fake"]
    )
    assert count == 2

    rows = (await db_session.execute(select(NewsItemModel))).scalars().all()
    assert {r.title for r in rows} == {"NVDA earnings beat", "NVDA roadmap update"}


async def test_ingest_unknown_provider_raises(db_session: AsyncSession) -> None:
    await _seed_universe(db_session)
    with pytest.raises(ValueError, match="Unknown news provider"):
        await fetch_news_for_symbol(db_session, "NVDA", providers=["does-not-exist"])


async def test_ingest_empty_provider_returns_zero(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_universe(db_session)
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: [])
    count = await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])
    assert count == 0


# ── Symbol tagging ───────────────────────────────────────────────────


async def test_target_symbol_always_tagged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """We asked for NVDA news — every article must land in (?, NVDA)
    even if the title doesn't literally mention NVDA."""
    await _seed_universe(db_session)
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: [_article(title="Generic chip industry update", url="https://ex.com/a")],
    )

    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    tags = (await db_session.execute(select(NewsSymbol))).scalars().all()
    assert {(t.symbol, t.news_id == _hash_id("https://ex.com/a")) for t in tags} == {
        ("NVDA", True)
    }


async def test_articles_get_tagged_to_other_mentioned_symbols(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A NVDA-fetch article that also mentions AMD should appear under
    both symbols. This is the join-table payoff."""
    await _seed_universe(db_session)
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: [
            _article(
                title="NVDA earnings drag AMD lower; AAPL flat",
                url="https://ex.com/a",
            )
        ],
    )

    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    nid = _hash_id("https://ex.com/a")
    rows = (
        await db_session.execute(
            select(NewsSymbol).where(NewsSymbol.news_id == nid)
        )
    ).scalars().all()
    assert {r.symbol for r in rows} == {"NVDA", "AMD", "AAPL"}


# ── Upsert / dedup ───────────────────────────────────────────────────


async def test_re_ingesting_same_url_does_not_duplicate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same URL → same hashed id → ON CONFLICT DO UPDATE, not duplicate."""
    await _seed_universe(db_session)
    art = _article(title="NVDA news v1", url="https://ex.com/a")
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: [art])

    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])
    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    rows = (await db_session.execute(select(NewsItemModel))).scalars().all()
    assert len(rows) == 1


async def test_restated_title_overwrites_existing_row(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same URL with a corrected title should update the row in place."""
    await _seed_universe(db_session)
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: [_article(title="NVDA news v1", url="https://ex.com/a")],
    )
    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: [_article(title="NVDA news v2 (corrected)", url="https://ex.com/a")],
    )
    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    rows = (await db_session.execute(select(NewsItemModel))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "NVDA news v2 (corrected)"


async def test_re_tagging_same_pair_does_not_duplicate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second ingest of the same article shouldn't try to re-INSERT
    the same (news_id, symbol) row — that would 23505 on the PK."""
    await _seed_universe(db_session)
    art = _article(title="NVDA news", url="https://ex.com/a")
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: [art])

    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])
    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    nid = _hash_id("https://ex.com/a")
    rows = (
        await db_session.execute(
            select(NewsSymbol).where(NewsSymbol.news_id == nid)
        )
    ).scalars().all()
    assert len(rows) == 1


# ── Provider isolation ───────────────────────────────────────────────


async def test_provider_failure_isolated_from_other_providers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One broken provider must not block another. The whole point of
    having two is fault tolerance."""
    await _seed_universe(db_session)

    def bad(_sym):
        raise RuntimeError("upstream is down")

    monkeypatch.setitem(PROVIDERS, "broken", bad)
    monkeypatch.setitem(
        PROVIDERS,
        "good",
        lambda _sym: [_article(title="NVDA news", url="https://ex.com/a")],
    )

    count = await fetch_news_for_symbol(
        db_session, "NVDA", providers=["broken", "good"]
    )
    assert count == 1

    rows = (await db_session.execute(select(NewsItemModel))).scalars().all()
    assert len(rows) == 1


# ── Observability ────────────────────────────────────────────────────


async def test_each_provider_call_is_logged(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    await _seed_universe(db_session)
    monkeypatch.setitem(
        PROVIDERS,
        "fake",
        lambda _sym: [_article(title="x", url="https://ex.com/a")],
    )

    with caplog.at_level(logging.INFO, logger="app.external"):
        await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.news"
    assert r.input_summary == {"symbol": "NVDA", "provider": "fake"}
    assert r.output_summary == {"article_count": 1}
    assert r.outcome == "ok"


# ── List endpoint integration ────────────────────────────────────────


async def test_list_news_filters_by_symbol(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: ingest two NVDA articles and one AMD-only article,
    confirm that GET /v1/news?symbol=NVDA returns only the NVDA ones."""
    from app.services.news_repository import list_news

    await _seed_universe(db_session)

    now = datetime.now(UTC)
    nvda_articles = [
        _article(
            title="NVDA news A",
            url="https://ex.com/a",
            ts=now - timedelta(minutes=10),
        ),
        _article(
            title="NVDA news B",
            url="https://ex.com/b",
            ts=now - timedelta(minutes=5),
        ),
    ]
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: nvda_articles)
    await fetch_news_for_symbol(db_session, "NVDA", providers=["fake"])

    amd_only = [_article(title="AMD by itself", url="https://ex.com/c")]
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym: amd_only)
    await fetch_news_for_symbol(db_session, "AMD", providers=["fake"])

    items, _ = await list_news(
        db_session, symbol="NVDA", hours=24, limit=50, cursor=None
    )
    titles = {i.title for i in items}
    assert titles == {"NVDA news A", "NVDA news B"}
    # Each item should carry NVDA in its symbols list, sorted/stable.
    for item in items:
        assert "NVDA" in item.symbols
