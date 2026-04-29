"""
Research-report endpoint.

Thin coordinator: parse the path + query, look up the same-day cache,
dispatch to the orchestrator on miss, write the fresh report back to
the cache, return it. Business logic (section composition, tool
fan-out, LLM synthesis, confidence stamping) lives in
``app.services.research_orchestrator``; cache I/O lives in
``app.services.research_cache``.

## Cache semantics

A successful synthesis is upserted into ``research_reports`` keyed on
``(symbol, focus, report_date)``. Subsequent calls within
``settings.RESEARCH_CACHE_MAX_AGE_HOURS`` (default 168 = 7 days)
re-serve the cached row instead of paying for another LLM round trip.
``?refresh=true`` skips the lookup but still upserts — same-day refresh
overwrites the existing row rather than duplicating.

``report_date`` is computed in ``settings.TZ`` (America/New_York), so
"same trading day" means same date in ET, not UTC. A request at 11pm
ET reads the same row a request at 9am ET the next morning UTC writes.

## Error mapping

- ``RuntimeError`` from the orchestrator → 503. The most common cause
  is ``ANTHROPIC_API_KEY`` not configured; "service up but dependency
  unavailable" is what 503 communicates. RFC 7807 problem+json carries
  the original message.
- Any other exception → 500 problem+json via the global handler in
  ``app.core.errors``.

## Rate limiting

Per-IP token bucket via ``enforce_research_rate_limit``. Default is
3 reports/hour/IP (env: ``RESEARCH_RATE_LIMIT_PER_HOUR``).

**The check runs AFTER the cache lookup, not before.** Cache hits do
NOT consume tokens — only cache misses and ``?refresh=true`` calls do.
The reasoning: the rate limit exists to bound *LLM cost*, and a cache
hit costs nothing. A user re-reading their already-generated report
should not be told they've hit a quota.

Trade-off: a determined attacker who has already burned 3 tokens can
still hit cache lookups indefinitely. For a personal-scale deployment
this is fine — cache lookups are sub-millisecond indexed SELECTs and
there's exactly one user. If/when this goes public-multi-user, flip
the dependency back to ``dependencies=[Depends(...)]`` on the route
decorator (Phase 3 decision; see README §"Rate limit posture").

Returns 429 + Retry-After on deny. Set the env var to 0 to disable
entirely.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import enforce_research_rate_limit, get_session
from app.core.auth import require_shared_secret
from app.core.settings import settings
from app.schemas.research import ResearchReport, ResearchReportSummary
from app.services import research_cache, research_orchestrator
from app.services.research_tool_registry import Focus

router = APIRouter()


@router.get(
    "/research",
    response_model=list[ResearchReportSummary],
    dependencies=[Depends(require_shared_secret)],
)
async def list_research(
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description=(
            "Page size. Capped at 100 so a single response stays cheap; "
            "the dashboard typically renders 20."
        ),
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Skip the first N rows. Combine with ``limit`` to paginate.",
    ),
    symbol: str | None = Query(
        None,
        max_length=16,
        description=(
            "Optional ticker filter. Uppercased before lookup so "
            "``?symbol=aapl`` finds AAPL rows."
        ),
    ),
    session: AsyncSession = Depends(get_session),
) -> list[ResearchReportSummary]:
    """List cached research reports newest-first for the dashboard sidebar.

    Lightweight metadata only — symbol, focus, report_date, generated_at,
    overall_confidence. Clicks on a row fetch the full report via
    ``POST /v1/research/{symbol}`` which hits the same-day cache.
    """
    return await research_cache.list_recent(
        session,
        limit=limit,
        offset=offset,
        symbol=symbol.upper() if symbol else None,
    )


@router.post(
    "/research/{symbol}",
    response_model=ResearchReport,
    dependencies=[Depends(require_shared_secret)],
)
async def research(
    request: Request,
    symbol: str,
    focus: Focus = Query(
        Focus.FULL,
        description=(
            "Report scope. ``full`` = 7 sections (Valuation, Quality, "
            "Capital Allocation, Earnings, Peers, Risk Factors, Macro). "
            "``earnings`` = 3 sections framed around an earnings event "
            "(Earnings, Valuation, Risk Factors)."
        ),
    ),
    refresh: bool = Query(
        False,
        description=(
            "If true, skip the same-day cache lookup and force a fresh "
            "synthesis. The fresh report still upserts into the cache, "
            "overwriting any same-day row. Use sparingly — every "
            "refresh=true call consumes a rate-limit token AND is a "
            "paid LLM round trip."
        ),
    ),
    session: AsyncSession = Depends(get_session),
) -> ResearchReport:
    """Generate (or re-serve) a structured research report for a ticker.

    Cost on cache hit: ~10 ms (one DB SELECT, no token consumed).
    Cost on miss: one rate-limit token + one Sonnet synthesis
    (~$0.05–$0.15) plus tool fan-out latency dominated by EDGAR
    (~5 s cold cache, sub-second warm).
    """
    target = symbol.upper()

    # Anchor the cache key in the configured trading timezone so a
    # 11pm-ET request and a 9am-ET request the next UTC morning still
    # land on the same logical day.
    tz = ZoneInfo(settings.TZ)
    report_date = datetime.now(tz).date()

    # Cache lookup runs first, unconditionally (cache hits are free —
    # no LLM cost, no token consumed). Only cache misses or explicit
    # ?refresh=true requests reach the rate limiter and the orchestrator.
    if not refresh:
        cached = await research_cache.lookup_recent(
            session,
            symbol=target,
            focus=focus.value,
            max_age_hours=settings.RESEARCH_CACHE_MAX_AGE_HOURS,
        )
        if cached is not None:
            return cached

    # Cache miss (or refresh forced) → about to spend an LLM call.
    # Rate-limit gate goes here, after we've confirmed we'd actually
    # be paying for the synthesis.
    await enforce_research_rate_limit(request)

    try:
        report = await research_orchestrator.compose_research_report(
            target, focus
        )
    except RuntimeError as exc:
        # Orchestration's upstream dependency (LLM provider, missing API
        # key) is unusable. Don't cache this — next request retries.
        raise HTTPException(
            status_code=503,
            detail=f"Research synthesis unavailable: {exc}",
        ) from exc

    await research_cache.upsert(
        session,
        symbol=target,
        focus=focus.value,
        report_date=report_date,
        report=report,
    )
    return report
