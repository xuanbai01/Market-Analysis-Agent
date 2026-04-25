"""
News ingestion. Mirrors the market-ingest pattern: a provider registry
of sync callables, each returning a list of normalised article dicts;
an async service that wraps them in ``asyncio.to_thread``, upserts
into ``news_items`` keyed on a stable hash of the URL, and tags each
article to one or more tracked symbols via ``news_symbols``.

Why hash-based ids: NewsAPI and Yahoo Finance RSS both return URLs but
not stable third-party ids. ``sha256(url).hexdigest()`` gives us a
deterministic 64-char id (matches our column width) that survives
reruns and dedupes the same article across providers.

Why two providers: NewsAPI is broad-market and queryable by phrase
(but rate-limited at 100 req/day on free tier); Yahoo Finance per-ticker
RSS is narrow but unlimited and naturally pre-tagged. They're
complementary and the cost of running both per request is one HTTP call
each. Add Reddit, MarketWatch, Benzinga later as the budget allows —
the registry shape is identical.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.core.settings import settings
from app.db.models.news import NewsItemModel
from app.db.models.news_symbols import NewsSymbol
from app.db.models.symbols import Symbol
from app.services.symbol_tagger import TrackedSymbol, tag

# Provider signature: (symbol_or_query) -> list of normalised dicts.
# Each dict has ``ts, title, url, source``. Sync by design — RSS parsing
# and HTTP libraries used here are blocking.
NewsProvider = Callable[[str], list[dict[str, Any]]]


def _hash_id(url: str) -> str:
    """Stable 64-char id from URL — fits news_items.id (varchar 64)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _fetch_newsapi(query: str) -> list[dict[str, Any]]:
    """
    Fetch up to 20 recent articles from NewsAPI dev tier matching ``query``.

    Returns ``[]`` (silently) when ``NEWSAPI_KEY`` is unset — the broader
    pipeline is fine without it because the RSS provider still works.
    Logs a warning rather than raising so a missing key doesn't 500 the
    research endpoint.
    """
    if not settings.NEWSAPI_KEY:
        return []

    resp = httpx.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "pageSize": 20,
            "sortBy": "publishedAt",
            "language": "en",
            "apiKey": settings.NEWSAPI_KEY,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()

    out: list[dict[str, Any]] = []
    for art in data.get("articles", []):
        url = art.get("url")
        if not url:
            continue
        out.append(
            {
                "ts": _parse_iso(art.get("publishedAt")) or datetime.now(UTC),
                "title": (art.get("title") or "").strip()[:512],
                "url": url[:1024],
                "source": (art.get("source") or {}).get("name", "newsapi")[:64],
            }
        )
    return out


def _fetch_rss_yahoo(symbol: str) -> list[dict[str, Any]]:
    """
    Fetch Yahoo Finance per-ticker RSS. URL pattern is documented and
    stable; returns up to ~25 recent items per call. No auth needed.
    """
    import feedparser  # noqa: PLC0415  — lazy import keeps tests fast

    feed_url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}"
        "&region=US&lang=en-US"
    )
    parsed = feedparser.parse(feed_url)

    out: list[dict[str, Any]] = []
    for entry in parsed.entries:
        url = entry.get("link")
        if not url:
            continue
        # feedparser exposes a published_parsed struct_time; fall back
        # to wall-clock when the feed omits it.
        ts = datetime.now(UTC)
        if entry.get("published_parsed"):
            ts = datetime(*entry.published_parsed[:6], tzinfo=UTC)
        out.append(
            {
                "ts": ts,
                "title": (entry.get("title") or "").strip()[:512],
                "url": url[:1024],
                "source": "yahoo_finance"[:64],
            }
        )
    return out


def _parse_iso(s: str | None) -> datetime | None:
    """Parse NewsAPI's ISO 8601 timestamps; None on absent/malformed."""
    if not s:
        return None
    try:
        # NewsAPI uses "...Z"; fromisoformat needs +00:00 in 3.11.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


PROVIDERS: dict[str, NewsProvider] = {
    "newsapi": _fetch_newsapi,
    "rss_yahoo": _fetch_rss_yahoo,
}


async def _load_tracked_symbols(session: AsyncSession) -> list[TrackedSymbol]:
    """All rows from ``symbols`` as TrackedSymbol — used by the tagger."""
    rows = (await session.execute(select(Symbol))).scalars().all()
    return [TrackedSymbol(symbol=r.symbol, name=r.name) for r in rows]


async def fetch_news_for_symbol(
    session: AsyncSession,
    symbol: str,
    *,
    providers: list[str] | None = None,
) -> int:
    """
    Fetch + upsert + tag news for a single symbol. Returns the number
    of articles ingested (sum across providers, before dedup — Postgres
    ON CONFLICT collapses dupes server-side).

    Auto-tags every fetched article to ``symbol`` (since we asked for
    it) and additionally runs the symbol tagger over title + source so
    a NewsAPI article mentioning both NVDA and AMD lands in
    ``news_symbols`` against both. The all-symbols pass is what makes
    a "newer NVDA article also mentions AMD" lookup work later when
    we render AMD's research page.

    Provider failures are isolated: if NewsAPI 500s, the RSS feed
    still contributes. Errors are logged via ``log_external_call`` and
    the provider returns an empty list to the caller.
    """
    chosen = providers if providers is not None else list(PROVIDERS.keys())
    unknown = [p for p in chosen if p not in PROVIDERS]
    if unknown:
        raise ValueError(
            f"Unknown news provider(s) {unknown!r}. Registered: {sorted(PROVIDERS)}"
        )

    tracked = await _load_tracked_symbols(session)
    target = symbol.upper()

    all_articles: list[dict[str, Any]] = []
    for provider_id in chosen:
        provider = PROVIDERS[provider_id]
        with log_external_call(
            f"{provider_id}.news",
            {"symbol": target, "provider": provider_id},
        ) as call:
            try:
                # Sync providers run under to_thread so the event loop
                # stays free for concurrent /v1/research/ calls.
                articles = await asyncio.to_thread(provider, target)
            except Exception as exc:  # noqa: BLE001 — provider isolation
                # Log and continue. One broken provider shouldn't take
                # the whole ingest down.
                call.record_output(
                    {"article_count": 0, "error_class": exc.__class__.__name__}
                )
                continue
            call.record_output({"article_count": len(articles)})
            all_articles.extend(articles)

    if not all_articles:
        return 0

    # Step 1 — upsert news_items. ON CONFLICT DO UPDATE so a re-fetch
    # picks up a corrected title or source without a duplicate row.
    rows = []
    for art in all_articles:
        rows.append(
            {
                "id": _hash_id(art["url"]),
                "ts": art["ts"],
                "title": art["title"],
                "url": art["url"],
                "source": art["source"],
            }
        )
    stmt = pg_insert(NewsItemModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "title": stmt.excluded.title,
            "url": stmt.excluded.url,
            "source": stmt.excluded.source,
        },
    )
    await session.execute(stmt)

    # Step 2 — symbol tagging. Always tag to the requested symbol (we
    # asked for it). Run the regex tagger over title to pick up any
    # other symbols that landed incidentally.
    tag_rows: list[dict[str, str]] = []
    for art in all_articles:
        news_id = _hash_id(art["url"])
        tagged_symbols = tag(art["title"], tracked) | {target}
        for sym in tagged_symbols:
            tag_rows.append({"news_id": news_id, "symbol": sym})

    if tag_rows:
        # Dedup at the (news_id, symbol) PK — re-tagging an article is
        # a no-op rather than an integrity error.
        tag_stmt = pg_insert(NewsSymbol).values(tag_rows)
        tag_stmt = tag_stmt.on_conflict_do_nothing(
            index_elements=["news_id", "symbol"]
        )
        await session.execute(tag_stmt)

    await session.commit()
    return len(all_articles)


async def ingest_news_once(session: AsyncSession) -> int:
    """
    Symbol-less variant — runs the registered providers across every
    tracked symbol. Used by ``POST /v1/news/ingest`` when no symbol is
    specified. Quadratic in (symbols × providers); fine while symbols
    is small. When the watchlist grows, switch to a scheduled per-symbol
    job (see todo backlog).
    """
    tracked = await _load_tracked_symbols(session)
    total = 0
    for sym in tracked:
        total += await fetch_news_for_symbol(session, sym.symbol)
    return total
