"""
Option tables (ADR 0008): one IV snapshot per symbol per trading day, and
the symbols whose options page was opened recently (which the daily run
also snapshots).

A snapshot row is written once and never updated: the first good row for
a (symbol, trading day) wins, like the rest of the stored market data
(docs/security.md A04). ``method_version`` says which method made its
figures, and ``detail`` keeps the raw near-money quotes they came from, so
a later method can be recomputed over the whole history. Open interest
and volume add up over the expiries the snapshot reads (around 30 and 90
days), not the whole chain; ``option_oi_totals`` holds whole-chain totals
for a short list of tickers, written once a session like the snapshots.

See ``alembic/versions/0004_option_snapshots.py`` and ``0005_option_oi_totals.py`` for the DDL.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class OptionIvSnapshot(Base):
    __tablename__ = "option_iv_snapshots"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    spot: Mapped[float] = mapped_column(Float, nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    iv30: Mapped[float | None] = mapped_column(Float)
    iv30_extrapolated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    iv90: Mapped[float | None] = mapped_column(Float)
    iv90_extrapolated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    skew25: Mapped[float | None] = mapped_column(Float)
    rv20: Mapped[float | None] = mapped_column(Float)
    rv60: Mapped[float | None] = mapped_column(Float)
    call_open_interest: Mapped[int] = mapped_column(BigInteger, nullable=False)
    put_open_interest: Mapped[int] = mapped_column(BigInteger, nullable=False)
    call_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    put_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_earnings: Mapped[date | None] = mapped_column(Date)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class OptionsTracked(Base):
    __tablename__ = "options_tracked"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_viewed: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OptionOiTotal(Base):
    """Open interest and volume summed over every listed expiry, one row a
    session, for ``OPTIONS_FULL_CHAIN_SYMBOLS``. ``expiries`` of ``listed``
    were read: fewer when Yahoo returned an expiry with a side missing."""

    __tablename__ = "option_oi_totals"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    call_open_interest: Mapped[int] = mapped_column(BigInteger, nullable=False)
    put_open_interest: Mapped[int] = mapped_column(BigInteger, nullable=False)
    call_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    put_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expiries: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    listed: Mapped[int] = mapped_column(SmallInteger, nullable=False)

