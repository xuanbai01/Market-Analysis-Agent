"""
SQLAlchemy model for the research-report same-day cache.

One row per (symbol, focus, report_date). ``report_json`` carries a
serialized ``ResearchReport`` — the cache layer writes via
``ResearchReport.model_dump(mode="json")`` and reads back via
``ResearchReport.model_validate(...)``. JSONB stays opaque to this
layer.

See ``alembic/versions/0003_research_reports.py`` for the DDL +
indexing rationale.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ResearchReportRow(Base):
    """One same-day cache entry. Composite PK; daily upsert semantics."""

    __tablename__ = "research_reports"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    focus: Mapped[str] = mapped_column(String(16), primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
