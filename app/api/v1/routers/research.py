"""
Research-report endpoint.

Thin router: parse the path + query, hand off to the orchestrator,
return the resulting ``ResearchReport``. Business logic — section
composition, tool fan-out, LLM synthesis, confidence stamping — lives
in ``app.services.research_orchestrator``.

## Error mapping

- ``RuntimeError`` from the orchestrator → 503. The most common cause
  is ``ANTHROPIC_API_KEY`` not configured; "service up but dependency
  unavailable" is what 503 communicates. The RFC 7807 problem+json
  body carries the original message so the operator sees it.
- Any other exception propagates to the global handler in
  ``app.core.errors`` → 500 problem+json.

## What the route deliberately does NOT do (yet)

- Same-day cache lookup → Phase 2.2b
- Rate limiting → Phase 2.2c

So this endpoint should not be exposed to public traffic before 2.2b
+ 2.2c land — every call is a fresh ~$0.05–$0.20 LLM round trip with
no de-dup. The route handler is intentionally minimal so the cache
middleware in 2.2b can wrap it cleanly.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.research import ResearchReport
from app.services import research_orchestrator
from app.services.research_tool_registry import Focus

router = APIRouter()


@router.post("/research/{symbol}", response_model=ResearchReport)
async def research(
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
) -> ResearchReport:
    """Generate a structured research report for a US-listed equity ticker.

    Symbol is uppercased before tool dispatch. Cost: one Haiku-class
    triage call (currently deterministic, no LLM) plus one Sonnet-class
    synthesis call. Response time is dominated by the slowest tool —
    typically EDGAR ~5 s for first 10-K fetch, sub-second on a warm
    cache.
    """
    try:
        return await research_orchestrator.compose_research_report(
            symbol.upper(), focus
        )
    except RuntimeError as exc:
        # Orchestration succeeded structurally but an upstream
        # dependency (LLM provider, missing API key) is not usable.
        raise HTTPException(
            status_code=503,
            detail=f"Research synthesis unavailable: {exc}",
        ) from exc
