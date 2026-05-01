"""
Tests for ``app.services.research_cache``.

DB-bound (uses the per-test session + tx-rollback fixture from conftest).
Two operations: ``lookup_recent`` reads the most-recent row inside a
time window, ``upsert`` writes / overwrites by (symbol, focus, date) PK.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.research_reports import ResearchReportRow
from app.schemas.research import (
    Claim,
    ClaimHistoryPoint,
    Confidence,
    ResearchReport,
    Section,
    Source,
)
from app.services.research_cache import list_recent, lookup_recent, upsert

# ── Fixtures ──────────────────────────────────────────────────────────


def _src() -> Source:
    return Source(tool="test.tool", fetched_at=datetime.now(UTC))


def _build_report(
    *, symbol: str = "AAPL", confidence: Confidence = Confidence.HIGH
) -> ResearchReport:
    """Minimal but valid ResearchReport for round-trip tests."""
    return ResearchReport(
        symbol=symbol,
        generated_at=datetime.now(UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[
                    Claim(description="Trailing P/E", value=28.5, source=_src()),
                ],
                summary="Trades at 28.5x trailing earnings.",
                confidence=confidence,
            ),
        ],
        overall_confidence=confidence,
        tool_calls_audit=["fetch_fundamentals: ok"],
    )


# ── upsert ────────────────────────────────────────────────────────────


async def test_upsert_writes_a_new_row(db_session: AsyncSession) -> None:
    report = _build_report()
    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        report=report,
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            ResearchReportRow.__table__.select().where(
                ResearchReportRow.symbol == "AAPL"
            )
        )
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "AAPL"
    assert row.focus == "full"
    assert row.report_date == date(2026, 4, 29)
    assert row.report_json["symbol"] == "AAPL"
    assert row.report_json["sections"][0]["title"] == "Valuation"


async def test_upsert_overwrites_same_day_row(db_session: AsyncSession) -> None:
    """Same (symbol, focus, report_date) — the second upsert replaces
    the first. This is what ?refresh=true relies on."""
    first = _build_report()
    first.sections[0].claims[0].value = 28.5  # type: ignore[misc]

    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        report=first,
    )
    await db_session.flush()

    second = _build_report()
    # Mutate so we can prove the second write wins.
    second.sections[0].summary = "Updated prose after refresh."
    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        report=second,
    )
    await db_session.flush()

    rows = (
        await db_session.execute(ResearchReportRow.__table__.select())
    ).all()
    assert len(rows) == 1, "same-day refresh should overwrite, not duplicate"
    assert (
        rows[0].report_json["sections"][0]["summary"]
        == "Updated prose after refresh."
    )


async def test_upsert_distinguishes_focus(db_session: AsyncSession) -> None:
    """Different focus values → different rows (focus is in the PK)."""
    rep = _build_report()
    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date(2026, 4, 29), report=rep,
    )
    await upsert(
        db_session, symbol="AAPL", focus="earnings",
        report_date=date(2026, 4, 29), report=rep,
    )
    await db_session.flush()

    rows = (
        await db_session.execute(ResearchReportRow.__table__.select())
    ).all()
    assert {(r.symbol, r.focus) for r in rows} == {
        ("AAPL", "full"),
        ("AAPL", "earnings"),
    }


# ── lookup_recent ─────────────────────────────────────────────────────


async def test_lookup_recent_returns_none_when_empty(
    db_session: AsyncSession,
) -> None:
    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )
    assert result is None


async def test_lookup_recent_returns_row_within_window(
    db_session: AsyncSession,
) -> None:
    """Row generated 1 hour ago must be returned by a 168-hour lookup."""
    report = _build_report()
    # Force generated_at to a known recent timestamp.
    report = report.model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date.today(),
        report=report,
    )
    await db_session.flush()

    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )
    assert result is not None
    assert isinstance(result, ResearchReport)
    assert result.symbol == "AAPL"
    assert result.sections[0].title == "Valuation"


async def test_lookup_recent_excludes_rows_older_than_window(
    db_session: AsyncSession,
) -> None:
    """A row from 200 hours ago does not satisfy a 168-hour window."""
    old_when = datetime.now(UTC) - timedelta(hours=200)
    old_report = _build_report().model_copy(update={"generated_at": old_when})

    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=(datetime.now(UTC) - timedelta(days=10)).date(),
        report=old_report,
    )
    await db_session.flush()

    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )
    assert result is None


async def test_lookup_recent_returns_most_recent_when_multiple_rows(
    db_session: AsyncSession,
) -> None:
    """If two rows fall inside the window, return the freshest."""
    older_when = datetime.now(UTC) - timedelta(hours=72)
    newer_when = datetime.now(UTC) - timedelta(hours=2)

    older = _build_report().model_copy(update={"generated_at": older_when})
    newer = _build_report().model_copy(update={"generated_at": newer_when})
    # Mark the newer one so we can identify it on read-back.
    newer.sections[0].summary = "freshest"

    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today() - timedelta(days=3), report=older,
    )
    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today(), report=newer,
    )
    await db_session.flush()

    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )
    assert result is not None
    assert result.sections[0].summary == "freshest"


async def test_lookup_recent_filters_by_symbol_and_focus(
    db_session: AsyncSession,
) -> None:
    """Cross-symbol / cross-focus rows must NOT be returned."""
    report = _build_report().model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    nvda_report = _build_report(symbol="NVDA").model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=1)}
    )

    # Wrong symbol
    await upsert(
        db_session, symbol="NVDA", focus="full",
        report_date=date.today(), report=nvda_report,
    )
    # Wrong focus
    await upsert(
        db_session, symbol="AAPL", focus="earnings",
        report_date=date.today(), report=report,
    )
    await db_session.flush()

    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )
    assert result is None


async def test_lookup_recent_zero_window_returns_none(
    db_session: AsyncSession,
) -> None:
    """max_age_hours=0 means 'cache disabled'. Always miss."""
    report = _build_report().model_copy(update={"generated_at": datetime.now(UTC)})
    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today(), report=report,
    )
    await db_session.flush()

    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=0
    )
    assert result is None


# ── Round-trip integrity ──────────────────────────────────────────────


async def test_round_trip_preserves_full_report_shape(
    db_session: AsyncSession,
) -> None:
    """A complex report serialized → JSONB → deserialized still validates
    as a ResearchReport with all its claims, sources, and confidence."""
    src1 = Source(
        tool="yfinance.fundamentals",
        fetched_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        url="https://finance.yahoo.com/quote/AAPL",
        detail="Ticker.info[trailingPE]",
    )
    src2 = Source(
        tool="sec.ten_k_risks_diff",
        fetched_at=datetime(2026, 4, 27, 9, 30, tzinfo=UTC),
        detail="0000320193-25-000079 vs 0000320193-24-000123",
    )
    report = ResearchReport(
        symbol="AAPL",
        generated_at=datetime(2026, 4, 29, 14, 5, tzinfo=UTC),
        sections=[
            Section(
                title="Valuation",
                claims=[
                    Claim(description="Trailing P/E", value=33.92, source=src1),
                    Claim(description="Forward P/E", value=28.62, source=src1),
                ],
                summary="Trades at 33.92x trailing.",
                confidence=Confidence.HIGH,
            ),
            Section(
                title="Risk Factors",
                claims=[
                    Claim(description="Added paragraphs", value=35, source=src2),
                ],
                summary="35 newly added risk paragraphs.",
                confidence=Confidence.MEDIUM,
            ),
        ],
        overall_confidence=Confidence.MEDIUM,
        tool_calls_audit=["fetch_fundamentals: ok", "extract_10k_risks_diff: ok"],
    )

    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        report=report,
    )
    await db_session.flush()

    result = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )

    assert result is not None
    assert result.symbol == "AAPL"
    assert len(result.sections) == 2
    assert result.sections[0].claims[0].source.url == "https://finance.yahoo.com/quote/AAPL"
    assert result.sections[1].claims[0].value == 35
    assert result.sections[1].confidence == Confidence.MEDIUM
    assert result.overall_confidence == Confidence.MEDIUM
    assert result.tool_calls_audit == [
        "fetch_fundamentals: ok",
        "extract_10k_risks_diff: ok",
    ]


# ── Phase 3.1: Claim.history round-trips through JSONB ───────────────


async def test_claim_history_round_trips_through_jsonb(
    db_session: AsyncSession,
) -> None:
    """A Claim with a populated ``history`` survives upsert -> lookup
    unchanged. This is the contract the frontend Sparkline reads off
    of — any drift in JSONB serialization here breaks the chart layer.
    """
    src = Source(
        tool="yfinance.fundamentals",
        fetched_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    history_bearing = Claim(
        description="EPS",
        value=2.18,
        source=src,
        history=[
            ClaimHistoryPoint(period="2023-Q4", value=1.46),
            ClaimHistoryPoint(period="2024-Q1", value=1.71),
            ClaimHistoryPoint(period="2024-Q2", value=1.89),
            ClaimHistoryPoint(period="2024-Q3", value=2.05),
            ClaimHistoryPoint(period="2024-Q4", value=2.18),
        ],
    )
    history_less = Claim(
        description="P/E",
        value=28.5,
        source=src,
        # No history -- mixed-shape report
    )

    report = ResearchReport(
        symbol="AAPL",
        generated_at=datetime(2026, 4, 29, 14, 5, tzinfo=UTC),
        sections=[
            Section(
                title="Earnings",
                claims=[history_bearing],
                summary="EPS rose from 1.46 to 2.18 over the last 5 quarters.",
                confidence=Confidence.HIGH,
            ),
            Section(
                title="Valuation",
                claims=[history_less],
                summary="Trades at 28.5x.",
                confidence=Confidence.HIGH,
            ),
        ],
        overall_confidence=Confidence.HIGH,
    )

    await upsert(
        db_session,
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        report=report,
    )
    await db_session.flush()

    restored = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )

    assert restored is not None
    # History-bearing claim survives.
    earnings_claim = restored.sections[0].claims[0]
    assert len(earnings_claim.history) == 5
    assert earnings_claim.history[0].period == "2023-Q4"
    assert earnings_claim.history[0].value == 1.46
    assert earnings_claim.history[-1].period == "2024-Q4"
    assert earnings_claim.history[-1].value == 2.18
    # History-less claim still works (defaults to empty list).
    valuation_claim = restored.sections[1].claims[0]
    assert valuation_claim.history == []


async def test_legacy_cache_row_without_history_key_still_parses(
    db_session: AsyncSession,
) -> None:
    """Backwards-compat: a row written before Phase 3.1 has no
    ``history`` key in the serialized claim. ``ResearchReport.model_validate``
    must accept it and fill in [].

    We simulate this by writing a raw JSONB payload that omits ``history``,
    then reading it back through ``lookup_recent``.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.models.research_reports import ResearchReportRow

    legacy_report_json = {
        "symbol": "AAPL",
        "generated_at": "2026-04-29T14:05:00+00:00",
        "sections": [
            {
                "title": "Valuation",
                "claims": [
                    {
                        "description": "P/E",
                        "value": 28.5,
                        "source": {
                            "tool": "yfinance.info",
                            "fetched_at": "2026-04-29T14:00:00+00:00",
                        },
                        # NOTE: no "history" key -- legacy shape
                    },
                ],
                "summary": "Trades at 28.5x.",
                "confidence": "high",
            },
        ],
        "overall_confidence": "high",
        "tool_calls_audit": [],
    }

    stmt = pg_insert(ResearchReportRow).values(
        symbol="AAPL",
        focus="full",
        report_date=date(2026, 4, 29),
        report_json=legacy_report_json,
        generated_at=datetime(2026, 4, 29, 14, 5, tzinfo=UTC),
    )
    await db_session.execute(stmt)
    await db_session.flush()

    restored = await lookup_recent(
        db_session, symbol="AAPL", focus="full", max_age_hours=168
    )
    assert restored is not None
    # Legacy shape parsed cleanly; the missing history defaulted to [].
    assert restored.sections[0].claims[0].history == []
    assert restored.sections[0].claims[0].value == 28.5


# ── Observability ─────────────────────────────────────────────────────


async def test_lookup_logs_external_call_with_hit_outcome(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    report = _build_report().model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=1)}
    )
    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today(), report=report,
    )
    await db_session.flush()

    with caplog.at_level(logging.INFO, logger="app.external"):
        await lookup_recent(
            db_session, symbol="AAPL", focus="full", max_age_hours=168
        )

    rec = next(
        r for r in caplog.records
        if r.name == "app.external" and r.service_id == "db.research_cache.lookup"
    )
    assert rec.input_summary == {
        "symbol": "AAPL", "focus": "full", "max_age_hours": 168,
    }
    assert rec.output_summary["hit"] is True


async def test_lookup_logs_miss_outcome(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="app.external"):
        await lookup_recent(
            db_session, symbol="AAPL", focus="full", max_age_hours=168
        )

    rec = next(
        r for r in caplog.records
        if r.name == "app.external" and r.service_id == "db.research_cache.lookup"
    )
    assert rec.output_summary["hit"] is False


async def test_upsert_logs_external_call(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="app.external"):
        await upsert(
            db_session, symbol="AAPL", focus="full",
            report_date=date.today(), report=_build_report(),
        )
        await db_session.flush()

    rec = next(
        r for r in caplog.records
        if r.name == "app.external" and r.service_id == "db.research_cache.upsert"
    )
    assert rec.input_summary["symbol"] == "AAPL"
    assert rec.input_summary["focus"] == "full"


# ── list_recent (Phase 3.0 A3) ────────────────────────────────────────


async def test_list_recent_empty_returns_empty_list(
    db_session: AsyncSession,
) -> None:
    rows = await list_recent(db_session, limit=20, offset=0)
    assert rows == []


async def test_list_recent_orders_by_generated_at_desc(
    db_session: AsyncSession,
) -> None:
    """Most-recent reports first — that's how the dashboard sidebar reads."""
    # Three reports across different (symbol, date) so PK doesn't collide.
    older = _build_report(symbol="AAPL").model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=72)}
    )
    middle = _build_report(symbol="MSFT").model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=24)}
    )
    newest = _build_report(symbol="NVDA").model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=1)}
    )

    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today() - timedelta(days=3), report=older,
    )
    await upsert(
        db_session, symbol="MSFT", focus="full",
        report_date=date.today() - timedelta(days=1), report=middle,
    )
    await upsert(
        db_session, symbol="NVDA", focus="full",
        report_date=date.today(), report=newest,
    )
    await db_session.flush()

    rows = await list_recent(db_session, limit=20, offset=0)
    assert [r.symbol for r in rows] == ["NVDA", "MSFT", "AAPL"]


async def test_list_recent_returns_summary_fields(
    db_session: AsyncSession,
) -> None:
    """Each row carries the 5 summary fields the dashboard renders."""
    report = _build_report(symbol="AAPL", confidence=Confidence.HIGH).model_copy(
        update={"generated_at": datetime.now(UTC) - timedelta(hours=2)}
    )
    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date(2026, 4, 29), report=report,
    )
    await db_session.flush()

    rows = await list_recent(db_session, limit=20, offset=0)

    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "AAPL"
    assert row.focus == "full"
    assert row.report_date == date(2026, 4, 29)
    assert row.overall_confidence == Confidence.HIGH
    # ``generated_at`` round-trips as a tz-aware datetime.
    assert row.generated_at.tzinfo is not None


async def test_list_recent_filters_by_symbol(
    db_session: AsyncSession,
) -> None:
    """``symbol=AAPL`` must exclude rows for other tickers."""
    aapl = _build_report(symbol="AAPL").model_copy(
        update={"generated_at": datetime.now(UTC)}
    )
    nvda = _build_report(symbol="NVDA").model_copy(
        update={"generated_at": datetime.now(UTC)}
    )
    await upsert(
        db_session, symbol="AAPL", focus="full",
        report_date=date.today(), report=aapl,
    )
    await upsert(
        db_session, symbol="NVDA", focus="full",
        report_date=date.today(), report=nvda,
    )
    await db_session.flush()

    rows = await list_recent(db_session, limit=20, offset=0, symbol="AAPL")

    assert [r.symbol for r in rows] == ["AAPL"]


async def test_list_recent_pagination(
    db_session: AsyncSession,
) -> None:
    """Limit + offset combine to slice the ordered list."""
    for i, sym in enumerate(["A", "B", "C", "D", "E"]):
        # Ensure deterministic ordering: A is oldest, E is newest.
        rep = _build_report(symbol=sym).model_copy(
            update={"generated_at": datetime.now(UTC) - timedelta(hours=10 - i)}
        )
        await upsert(
            db_session, symbol=sym, focus="full",
            report_date=date.today() - timedelta(days=10 - i), report=rep,
        )
    await db_session.flush()

    page1 = await list_recent(db_session, limit=2, offset=0)
    page2 = await list_recent(db_session, limit=2, offset=2)
    page3 = await list_recent(db_session, limit=2, offset=4)

    # Newest first → E, D, C, B, A.
    assert [r.symbol for r in page1] == ["E", "D"]
    assert [r.symbol for r in page2] == ["C", "B"]
    assert [r.symbol for r in page3] == ["A"]


async def test_list_recent_logs_external_call(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """A09: list operations log under db.research_cache.list."""
    import logging

    with caplog.at_level(logging.INFO, logger="app.external"):
        await list_recent(db_session, limit=10, offset=0, symbol="AAPL")

    rec = next(
        r for r in caplog.records
        if r.name == "app.external" and r.service_id == "db.research_cache.list"
    )
    assert rec.input_summary == {
        "limit": 10, "offset": 0, "symbol": "AAPL",
    }
    # ``count`` is the number of rows returned — useful for debugging.
    assert rec.output_summary["count"] == 0
