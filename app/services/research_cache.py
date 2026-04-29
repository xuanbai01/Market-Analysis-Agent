"""
Same-day cache for research reports.

Two operations:

- ``lookup_recent`` reads the most-recent ``ResearchReport`` for a
  ``(symbol, focus)`` pair within a time window
  (``max_age_hours``). Returns None on miss.
- ``upsert`` writes a fresh report under ``(symbol, focus, report_date)``
  with ON CONFLICT DO UPDATE so a same-day ``?refresh=true`` overwrites
  rather than duplicates.

JSONB stores the serialized ``ResearchReport``. The cache layer is
opaque to the report's internal structure — anything that round-trips
through ``model_dump(mode="json")`` and ``model_validate(...)`` works
unchanged.

## Why time-based lookup, daily-keyed write

The PK has ``report_date`` (DATE) so a single calendar day can have at
most one row per (symbol, focus) — clean upsert semantics for
``?refresh=true``. The lookup query, however, compares against
``generated_at`` (TIMESTAMPTZ) so the cache window is precisely
hour-grained: ``max_age_hours=168`` returns rows generated within the
last 7 days, not "today's row OR yesterday's row OR ...". This
decoupling lets us tune the cache window via env var
(``RESEARCH_CACHE_MAX_AGE_HOURS``) without changing the schema.

## Observability

Both operations emit ``log_external_call`` records under the
``db.research_cache.{lookup,upsert}`` service ids. ``lookup`` records
``hit=True/False`` so cache hit-rate is queryable from the A09 stream.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.db.models.research_reports import ResearchReportRow
from app.schemas.research import ResearchReport


async def lookup_recent(
    session: AsyncSession,
    *,
    symbol: str,
    focus: str,
    max_age_hours: int,
) -> ResearchReport | None:
    """Return the freshest cached report inside the time window, or None.

    ``max_age_hours <= 0`` is treated as "cache disabled" — always
    returns None without touching the DB. Useful for tests and for
    operators who want to disable caching without dropping the table.
    """
    with log_external_call(
        "db.research_cache.lookup",
        {"symbol": symbol, "focus": focus, "max_age_hours": max_age_hours},
    ) as call:
        if max_age_hours <= 0:
            call.record_output({"hit": False, "reason": "cache_disabled"})
            return None

        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        stmt = (
            select(ResearchReportRow)
            .where(
                ResearchReportRow.symbol == symbol,
                ResearchReportRow.focus == focus,
                ResearchReportRow.generated_at >= cutoff,
            )
            .order_by(ResearchReportRow.generated_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()

        if row is None:
            call.record_output({"hit": False})
            return None

        call.record_output(
            {
                "hit": True,
                "report_date": row.report_date.isoformat(),
                "age_hours": (
                    datetime.now(UTC) - row.generated_at
                ).total_seconds()
                / 3600.0,
            }
        )
        return ResearchReport.model_validate(row.report_json)


async def upsert(
    session: AsyncSession,
    *,
    symbol: str,
    focus: str,
    report_date: date,
    report: ResearchReport,
) -> None:
    """Insert or overwrite the (symbol, focus, report_date) row.

    Same-day refresh semantics: ``ON CONFLICT (symbol, focus,
    report_date) DO UPDATE`` so ``?refresh=true`` replaces the
    existing row instead of duplicating.
    """
    with log_external_call(
        "db.research_cache.upsert",
        {
            "symbol": symbol,
            "focus": focus,
            "report_date": report_date.isoformat(),
        },
    ) as call:
        report_json = report.model_dump(mode="json")
        stmt = pg_insert(ResearchReportRow).values(
            symbol=symbol,
            focus=focus,
            report_date=report_date,
            report_json=report_json,
            generated_at=report.generated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "focus", "report_date"],
            set_={
                "report_json": stmt.excluded.report_json,
                "generated_at": stmt.excluded.generated_at,
            },
        )
        await session.execute(stmt)
        await session.commit()
        call.record_output({"written": True})
