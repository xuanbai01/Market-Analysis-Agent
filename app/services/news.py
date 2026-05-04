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

## Why no upstream-provider call from here

The dashboard reads whatever the ingest job has written to DB.
Triggering a fresh provider fetch from inside research_orchestrator
would (a) couple the LLM-cost path to NewsAPI/RSS rate limits and
(b) make a single research request an order of magnitude slower.
``POST /v1/news/ingest`` stays the seam where new articles enter the
system. If dogfooding shows users see stale news, revisit by running
ingest opportunistically from inside ``fetch_news``.

## Failure modes

- No news for the symbol → ``{}`` returned. The section builder
  emits an empty claims list; the orchestrator's confidence scorer
  marks the News section LOW.
- Categorizer raises → each article still ships as a Claim with
  ``category=other, sentiment=neutral``. The card degrades but
  doesn't disappear.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.observability import log_external_call
from app.db.session import SessionLocal
from app.schemas.research import Claim, Source
from app.services.news_categorizer import categorize_news_headlines
from app.services.news_repository import list_news

_HOURS_LOOKBACK = 168  # 7 days
_LIMIT = 30  # latest N articles per symbol


async def fetch_news(symbol: str) -> dict[str, Claim]:
    """Pull the symbol's recent news as a dict of citation-bearing
    Claims. See module docstring."""
    target = symbol.upper()
    service_id = "research.news_query"

    with log_external_call(
        service_id, {"symbol": target, "hours": _HOURS_LOOKBACK, "limit": _LIMIT}
    ) as call:
        # Open a fresh session — orchestrator tools don't share one.
        async with SessionLocal() as session:
            items, _ = await list_news(
                session,
                symbol=target,
                hours=_HOURS_LOOKBACK,
                limit=_LIMIT,
                cursor=None,
            )
        call.record_output({"item_count": len(items)})

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
