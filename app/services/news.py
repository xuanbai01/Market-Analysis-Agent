"""
News orchestrator-tool. Phase 4.4.A.

Wraps ``news_repository.list_news`` + ``news_categorizer`` into the
``Callable[[str], Awaitable[dict[str, Claim]]]`` shape the research
orchestrator expects. Opens its own AsyncSession internally so it
slots into ``TOOL_DISPATCH`` alongside the other (session-less)
tools.

## Why this is a separate module from news_ingestion / news_repository

- ``news_ingestion`` writes to the ``news_items`` + ``news_symbols``
  tables (provider-side). It's the cron / `POST /v1/news/ingest`
  endpoint's path.
- ``news_repository`` reads from those tables, returning typed
  ``NewsItemOut`` records. It's the `GET /v1/news` endpoint's path.
- ``news`` (this module) is the *research-time* path: it queries via
  ``news_repository.list_news`` for the symbol's last 7 days of
  articles, runs them through the Haiku categorizer, and emits one
  ``Claim`` per article so the citation-discipline rubric can verify
  the news section's prose against the article list.

## Ingest before reading (2026-11)

The original design read only what ``POST /v1/news/ingest`` had written,
to keep provider calls off the research path. Nothing ever called that
endpoint in production, so the News card stayed empty. ``fetch_news``
now pulls the symbol's latest headlines first (``fetch_news_for_symbol``:
Yahoo RSS, plus NewsAPI when keyed). It's one cheap call per *fresh*
report — reports are cached for 7 days and fresh ones are rate-limited
— and it runs concurrently with the other tools in the orchestrator's
fan-out. It's bounded by ``_INGEST_TIMEOUT_SECONDS`` because
feedparser's fetch has no timeout of its own, and any ingest failure
degrades to reading whatever the DB already holds.

## Failure modes

- Ingest fails or stalls → logged as ``ingest_error`` on the
  ``research.news_query`` record; the read proceeds.
- No news for the symbol → ``{}`` returned. The section builder
  emits an empty claims list; the orchestrator's confidence scorer
  marks the News section LOW.
- Categorizer raises → each article still ships as a Claim with
  ``category=other, sentiment=neutral``. The card degrades but
  doesn't disappear.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.core.observability import log_external_call
from app.db.session import SessionLocal
from app.schemas.research import Claim, Source
from app.services.news_categorizer import categorize_news_headlines
from app.services.news_ingestion import fetch_news_for_symbol
from app.services.news_repository import list_news

_HOURS_LOOKBACK = 168  # 7 days
_LIMIT = 30  # latest N articles per symbol
# Upper bound on the pre-read ingest. The RSS fetch has no timeout of
# its own; the slowest other tool (10-K diff) takes seconds to tens of
# seconds, so 15 s keeps news off the critical path.
_INGEST_TIMEOUT_SECONDS = 15.0


async def _ingest_latest(symbol: str) -> dict[str, Any]:
    """Pull the symbol's newest headlines into the DB. Never raises:
    returns the observability fields describing what happened."""
    try:
        async with SessionLocal() as session:
            count = await asyncio.wait_for(
                fetch_news_for_symbol(session, symbol),
                timeout=_INGEST_TIMEOUT_SECONDS,
            )
    except Exception as exc:  # noqa: BLE001 — degrade to the DB read
        return {"ingested": 0, "ingest_error": exc.__class__.__name__}
    return {"ingested": count}


async def fetch_news(symbol: str) -> dict[str, Claim]:
    """Pull the symbol's recent news as a dict of citation-bearing
    Claims. See module docstring."""
    target = symbol.upper()
    service_id = "research.news_query"

    with log_external_call(
        service_id, {"symbol": target, "hours": _HOURS_LOOKBACK, "limit": _LIMIT}
    ) as call:
        ingest_summary = await _ingest_latest(target)
        # Open a fresh session — orchestrator tools don't share one.
        async with SessionLocal() as session:
            items, _ = await list_news(
                session,
                symbol=target,
                hours=_HOURS_LOOKBACK,
                limit=_LIMIT,
                cursor=None,
            )
        call.record_output({**ingest_summary, "item_count": len(items)})

    if not items:
        return {}

    # Categorize each headline. If the categorizer raises (rate limit,
    # network, schema), fall back to per-article defaults so the
    # section still ships.
    headlines = [item.title for item in items]
    classifications: dict[int, dict[str, str]]
    try:
        classifications = await categorize_news_headlines(headlines)
    except Exception:
        classifications = {}

    fetched_at = datetime.now(UTC)

    out: dict[str, Claim] = {}
    for i, item in enumerate(items):
        cls = classifications.get(
            i, {"category": "other", "sentiment": "neutral"}
        )

        # NewsItemOut.ts is an ISO string. Use it for the source's
        # fetched_at so the citation reflects when the article was
        # published, not when we queried.
        try:
            published_at = datetime.fromisoformat(item.ts)
        except ValueError:
            published_at = fetched_at

        out[f"news_{i}"] = Claim(
            description=item.title[:200],  # schema cap
            value=cls["sentiment"],
            source=Source(
                tool=f"{item.source}.news",
                fetched_at=published_at,
                url=str(item.url),
                detail=f"category={cls['category']}",
            ),
            unit="string",
        )
    return out
