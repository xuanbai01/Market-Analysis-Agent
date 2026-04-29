"""research_reports table for the same-day cache

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29

Stores one row per (symbol, focus, report_date). The agent endpoint
writes here on every successful synthesis; subsequent requests for the
same (symbol, focus) within ``RESEARCH_CACHE_MAX_AGE_HOURS`` (default
168 = 7 days) read this table instead of paying for another LLM call.

## Two date columns, two purposes

- ``report_date`` (DATE) — daily-granular cache key, anchored in
  ``settings.TZ`` (America/New_York). Part of the PK so a same-day
  ``?refresh=true`` upserts the existing row rather than piling on
  duplicates.
- ``generated_at`` (TIMESTAMPTZ) — precise wall-clock when the LLM
  synthesis returned. Used by the cache lookup's time-window query
  (``generated_at >= now() - max_age_hours``) so sub-day or
  multi-day cache windows both work without schema change.

## Why JSONB

JSONB stores ``ResearchReport.model_dump_json()`` directly — no
relational decomposition into sections / claims / sources tables. The
report is opaque to the cache layer; deserialization happens via
``ResearchReport.model_validate_json()`` on read. JSONB over TEXT
buys us free indexability into report fields later (e.g. "find every
report where overall_confidence='high'") at zero cost on disk.

## Indexes

- PK ``(symbol, focus, report_date)`` covers daily upsert + most
  same-day lookups.
- ``ix_research_reports_lookup`` on ``(symbol, focus, generated_at DESC)``
  covers the time-window cache lookup pattern.
- Yesterday's rows are deliberately retained — a future cleanup job
  can ``DELETE WHERE report_date < ?`` cheaply via the index.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_reports",
        sa.Column("symbol", sa.String(length=16), primary_key=True),
        sa.Column("focus", sa.String(length=16), primary_key=True),
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column(
            "report_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    # Time-window cache lookup: WHERE symbol=? AND focus=?
    # AND generated_at >= ? ORDER BY generated_at DESC LIMIT 1.
    op.create_index(
        "ix_research_reports_lookup",
        "research_reports",
        ["symbol", "focus", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_research_reports_lookup", table_name="research_reports")
    op.drop_table("research_reports")
