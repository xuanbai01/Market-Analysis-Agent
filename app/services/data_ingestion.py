"""
Ingestion services.

Each provider is a **sync** function that takes ``(symbol, period)`` and
returns a list of bar dicts with keys ``ts, open, high, low, close,
volume``. The async service wraps the provider in ``asyncio.to_thread``
and upserts the bars into the ``candles`` table. New providers (Polygon,
Alpha Vantage, etc.) drop in by registering under a new key in
``PROVIDERS``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.db.models.candles import Candle

# Provider signature: (symbol, period) -> list[dict] where each dict has
# the keys ``ts, open, high, low, close, volume``. Sync by design —
# most market-data libs (yfinance, pandas_datareader) are blocking.
Provider = Callable[[str, str], list[dict[str, Any]]]


def _fetch_yfinance_bars(symbol: str, period: str) -> list[dict[str, Any]]:
    """
    Fetch daily OHLCV bars from Yahoo Finance.

    yfinance is imported lazily so the test suite can swap in a fake
    provider without installing yfinance or paying its pandas/numpy
    import cost.
    """
    import yfinance  # noqa: PLC0415  (intentional lazy import)

    ticker = yfinance.Ticker(symbol)
    df = ticker.history(period=period, auto_adjust=False)

    bars: list[dict[str, Any]] = []
    # df.index is a DatetimeIndex; iterrows gives (Timestamp, Series).
    for ts, row in df.iterrows():
        bars.append(
            {
                "ts": ts.to_pydatetime(),  # tz-aware (yfinance attaches a tz)
                "open": Decimal(str(row["Open"])),
                "high": Decimal(str(row["High"])),
                "low": Decimal(str(row["Low"])),
                "close": Decimal(str(row["Close"])),
                "volume": int(row["Volume"]),
            }
        )
    return bars


# Registry keyed by provider id. Tests add a fake via `monkeypatch.setitem`.
PROVIDERS: dict[str, Provider] = {
    "yfinance": _fetch_yfinance_bars,
}


async def ingest_market_data(
    session: AsyncSession,
    symbol: str,
    period: str,
    provider: str,
    interval: str = "1d",
) -> int:
    """
    Fetch OHLCV bars from ``provider`` for ``symbol`` over ``period``
    and upsert them into the ``candles`` table.

    Upsert on the composite PK ``(symbol, ts, interval)`` — if a
    provider restates a bar we overwrite with the latest values rather
    than failing on a duplicate key.

    Returns the number of bars received from the provider (not the
    number of brand-new rows — Postgres doesn't distinguish insert vs
    update for ON CONFLICT DO UPDATE without extra plumbing).
    """
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    fetch = PROVIDERS[provider]

    with log_external_call(
        f"{provider}.history",
        {"symbol": symbol, "period": period, "interval": interval},
    ) as call:
        # Block off the event loop — yfinance / requests are sync.
        bars = await asyncio.to_thread(fetch, symbol, period)
        call.record_output({"bar_count": len(bars)})

    if not bars:
        return 0

    rows = [
        {
            "symbol": symbol.upper(),
            "interval": interval,
            "ts": bar["ts"],
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
        }
        for bar in bars
    ]

    stmt = pg_insert(Candle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "ts", "interval"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def ingest_news_once(session: AsyncSession) -> int:
    """
    Story 1 stub — real implementation lands with the news provider work.
    Kept here so the POST /v1/news/ingest endpoint has something to call.
    """
    # TODO: implement NewsAPI / RSS ingest with dedup
    _ = session  # silence unused-arg lint
    return 0
