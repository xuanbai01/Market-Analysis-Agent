"""
Earnings tool. Returns latest-quarter EPS snapshot + ~20-quarter history
(via ``Claim.history``) + forward consensus + summary stats as a flat
``dict[str, Claim]``.

## Shape (Phase 3.2.E)

The pre-3.2.E shape used per-quarter prefix keys (``q1.eps_actual``,
``q2.eps_actual``, ...) which was awkward when Phase 3 added quarterly
sparklines. After 3.2.E:

- Three history-bearing claims (``eps_actual``, ``eps_estimate``,
  ``eps_surprise_pct``) carry up to 20 quarters in ``Claim.history``.
- ``latest_report_date`` is a separate string label for the most-recent
  reporting event.
- ``next.report_date`` / ``next.eps_estimate`` / ``next.revenue_estimate``
  are forward-only (no history — analyst revisions are noisy and
  surfacing them as a sparkline confuses readers).
- ``last_20q.beat_count`` / ``last_20q.avg_surprise_pct`` summarize the
  history into single agent-readable scalars.

9 keys total, down from 21. Agent prompt is dramatically simpler.

## Why ``get_earnings_dates(limit=24)`` not the property

``Ticker.earnings_dates`` defaults to ~8 rows; ``get_earnings_dates(limit=24)``
asks for ~24, which gives us roughly 6 years of past quarters on
mature symbols. We cap our history at 20 quarters (the catalog target);
the extra rows handle yfinance's mix of past + scheduled-future entries.

## Why no transcript / 8-K text

See ADR 0003 §"Free-data fatigue": transcript scrapers are exactly the
"fragile, breaks at the worst time" surface that costs more in flake
than it gives in signal. Structured numbers from ``earnings_dates`` are
enough to compose an analyst-shaped Earnings section.

## Why no persistence

Earnings actuals for past quarters are settled and won't change. Forward
estimates move as analysts revise — but for an on-demand research tool,
fresh fetches are cheap and avoid the "stale forward estimate" failure
mode.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.observability import log_external_call
from app.schemas.research import Claim, ClaimHistoryPoint, ClaimValue, Source
from app.services.fundamentals_history import format_period

# How far back to keep in ``Claim.history``. yfinance can return more
# than this; we cap so the chart stays readable and JSONB cache rows
# don't bloat unnecessarily.
HISTORY_LIMIT_QUARTERS: int = 20

# How many rows to ask yfinance for. We pad above ``HISTORY_LIMIT_QUARTERS``
# because ``get_earnings_dates`` returns past + scheduled-future rows
# in one frame; future rows have NaN ``Reported EPS`` and we filter them
# out before slicing.
EARNINGS_DATES_FETCH_LIMIT: int = 24


# ── Stable claim contract ─────────────────────────────────────────────

# History-bearing claims. The frontend renders sparklines next to these;
# the snapshot value matches ``history[-1].value`` by construction.
HISTORY_KEYS: tuple[str, ...] = (
    "eps_actual",
    "eps_estimate",
    "eps_surprise_pct",
)

# All claim keys this tool produces. Ordered for deterministic iteration;
# the agent reads by key, not position.
CLAIM_KEYS: tuple[str, ...] = (
    # Latest-quarter snapshot label.
    "latest_report_date",
    # History-bearing per-quarter metrics.
    *HISTORY_KEYS,
    # Forward consensus (no history — revision drift is noisy).
    "next.report_date",
    "next.eps_estimate",
    "next.revenue_estimate",
    # Computed summaries over the history.
    "last_20q.beat_count",
    "last_20q.avg_surprise_pct",
)


_DESCRIPTIONS: dict[str, str] = {
    "latest_report_date": "Most recent earnings report date",
    "eps_actual": "Reported EPS (latest quarter)",
    "eps_estimate": "Consensus EPS estimate (latest quarter, going in)",
    "eps_surprise_pct": "EPS surprise % (latest quarter)",
    "next.report_date": "Next earnings report date (expected)",
    "next.eps_estimate": "Next quarter consensus EPS estimate",
    "next.revenue_estimate": "Next quarter consensus revenue estimate",
    "last_20q.beat_count": (
        "Number of EPS beats over the last 20 quarters (or fewer if"
        " history is shorter)"
    ),
    "last_20q.avg_surprise_pct": (
        "Average EPS surprise (%) over the last 20 quarters of history"
    ),
}


_DETAILS: dict[str, str] = {
    "latest_report_date": "earnings_dates index (newest non-null Reported EPS)",
    "eps_actual": "earnings_dates[Reported EPS]",
    "eps_estimate": "earnings_dates[EPS Estimate]",
    "eps_surprise_pct": "earnings_dates[Surprise(%)] (or computed)",
    "next.report_date": "calendar[Earnings Date]",
    "next.eps_estimate": "earnings_estimate[+1q].avg",
    "next.revenue_estimate": "earnings_estimate[+1q].revenueAvg",
    "last_20q.beat_count": (
        "computed: count of past quarters with surprise > 0,"
        " capped at last 20"
    ),
    "last_20q.avg_surprise_pct": (
        "computed: mean of past quarters' non-null surprises, capped at last 20"
    ),
}


# Provider signature: returns ``(values, history_map)``. Sync — yfinance
# is blocking; the async entry point hands it to ``to_thread``. Mirrors
# the fetch_fundamentals provider shape so a future refactor that
# unifies them is mechanical.
EarningsProvider = Callable[
    [str],
    tuple[
        dict[str, ClaimValue | None],
        dict[str, list[ClaimHistoryPoint]],
    ],
]


# ── yfinance provider ─────────────────────────────────────────────────


def _safe_attr(ticker: Any, name: str) -> Any:
    """Return ``ticker.<name>`` or None if access raises (yfinance is flaky)."""
    try:
        return getattr(ticker, name, None)
    except Exception:  # noqa: BLE001 — yfinance lookups occasionally throw
        return None


def _safe_float(value: Any) -> float | None:
    """Coerce to float, return None on NaN / non-numeric / None."""
    if value is None:
        return None
    try:
        import pandas as pd  # noqa: PLC0415

        if pd.isna(value):
            return None
    except ImportError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_earnings_dates(ticker: Any) -> Any:
    """Fetch ~24 rows of earnings dates with one HTTP call.

    Prefers ``get_earnings_dates(limit=24)`` (the wider-history method);
    falls back to the ``earnings_dates`` property on yfinance versions
    that don't expose the method. Returns None on any failure — the
    caller treats None as "no history available".
    """
    method = getattr(ticker, "get_earnings_dates", None)
    if callable(method):
        try:
            return method(limit=EARNINGS_DATES_FETCH_LIMIT)
        except Exception:  # noqa: BLE001
            pass
    return _safe_attr(ticker, "earnings_dates")


def _extract_eps_history(earnings_dates: Any) -> tuple[
    dict[str, ClaimValue | None], dict[str, list[ClaimHistoryPoint]]
]:
    """Pull past-quarter EPS history from yfinance's earnings_dates frame.

    Returns ``(snapshot_values, history_map)``:

    - snapshot_values: ``{latest_report_date, eps_actual, eps_estimate,
      eps_surprise_pct}`` for the most recent past quarter (or None
      keys when no past data exists).
    - history_map: lists of ``ClaimHistoryPoint`` for the three
      history-bearing claims, oldest → newest, capped at
      ``HISTORY_LIMIT_QUARTERS`` quarters.

    Past = ``Reported EPS`` is non-NaN. yfinance fills future rows
    with NaN since the same DataFrame mixes past + scheduled events.
    """
    snapshot: dict[str, ClaimValue | None] = {
        "latest_report_date": None,
        "eps_actual": None,
        "eps_estimate": None,
        "eps_surprise_pct": None,
    }
    history: dict[str, list[ClaimHistoryPoint]] = {k: [] for k in HISTORY_KEYS}

    if earnings_dates is None or getattr(earnings_dates, "empty", True):
        return snapshot, history

    import pandas as pd  # noqa: PLC0415

    if "Reported EPS" not in earnings_dates.columns:
        return snapshot, history

    # Filter to rows that have a real Reported EPS value.
    past_mask = earnings_dates["Reported EPS"].apply(lambda v: not pd.isna(v))
    past = earnings_dates[past_mask].copy()
    if past.empty:
        return snapshot, history

    # Sort newest-first for the snapshot pick, then take the most-recent
    # ``HISTORY_LIMIT_QUARTERS`` rows for history.
    past = past.sort_index(ascending=False)
    past_capped = past.head(HISTORY_LIMIT_QUARTERS)

    has_surprise_col = "Surprise(%)" in past_capped.columns

    # Snapshot from the newest row.
    newest_idx = past_capped.index[0]
    newest_row = past_capped.iloc[0]
    try:
        snapshot["latest_report_date"] = newest_idx.date().isoformat()
    except AttributeError:
        snapshot["latest_report_date"] = str(newest_idx)
    snapshot["eps_actual"] = _safe_float(newest_row.get("Reported EPS"))
    snapshot["eps_estimate"] = _safe_float(newest_row.get("EPS Estimate"))
    snapshot["eps_surprise_pct"] = _surprise_for_row(
        newest_row, has_surprise_col
    )

    # History: iterate over capped past rows oldest → newest.
    for idx, row in past_capped.sort_index(ascending=True).iterrows():
        period = format_period(idx)
        actual = _safe_float(row.get("Reported EPS"))
        estimate = _safe_float(row.get("EPS Estimate"))
        surprise = _surprise_for_row(row, has_surprise_col)
        if actual is not None:
            history["eps_actual"].append(
                ClaimHistoryPoint(period=period, value=actual)
            )
        if estimate is not None:
            history["eps_estimate"].append(
                ClaimHistoryPoint(period=period, value=estimate)
            )
        if surprise is not None:
            history["eps_surprise_pct"].append(
                ClaimHistoryPoint(period=period, value=surprise)
            )

    return snapshot, history


def _surprise_for_row(row: Any, has_surprise_col: bool) -> float | None:
    """yfinance's ``Surprise(%)`` when present, else derived from
    (Reported - Estimate) / |Estimate| × 100. None when neither path
    yields a real number."""
    if has_surprise_col:
        s = _safe_float(row.get("Surprise(%)"))
        if s is not None:
            return s
    actual = _safe_float(row.get("Reported EPS"))
    estimate = _safe_float(row.get("EPS Estimate"))
    if actual is not None and estimate not in (None, 0):
        return (actual - estimate) / abs(estimate) * 100.0
    return None


def _extract_forward(
    earnings_estimate: Any, calendar: Any
) -> dict[str, ClaimValue | None]:
    """Forward EPS + revenue + report date.

    Same logic as before 3.2.E — yfinance's earnings_estimate is
    indexed by period label ('0q', '+1q', '0y', '+1y'); '+1q' is the
    next reporting quarter. Calendar is sometimes a list and sometimes
    a single date; both are handled.
    """
    out: dict[str, ClaimValue | None] = {
        "next.report_date": None,
        "next.eps_estimate": None,
        "next.revenue_estimate": None,
    }

    if (
        earnings_estimate is not None
        and not getattr(earnings_estimate, "empty", True)
        and "+1q" in getattr(earnings_estimate, "index", [])
    ):
        row = earnings_estimate.loc["+1q"]
        out["next.eps_estimate"] = _safe_float(row.get("avg"))
        out["next.revenue_estimate"] = _safe_float(row.get("revenueAvg"))

    if isinstance(calendar, dict):
        raw_date = calendar.get("Earnings Date")
        if isinstance(raw_date, list) and raw_date:
            raw_date = raw_date[0]
        if raw_date is not None:
            try:
                out["next.report_date"] = raw_date.isoformat()
            except AttributeError:
                out["next.report_date"] = str(raw_date)

    return out


def _fetch_yfinance_earnings(
    symbol: str,
) -> tuple[dict[str, ClaimValue | None], dict[str, list[ClaimHistoryPoint]]]:
    """Pull earnings_dates + earnings_estimate + calendar from yfinance once.

    Returns the (values, history_map) tuple shape that matches the
    fetch_fundamentals provider contract.
    """
    import yfinance  # noqa: PLC0415

    ticker = yfinance.Ticker(symbol)
    earnings_dates = _get_earnings_dates(ticker)
    earnings_estimate = _safe_attr(ticker, "earnings_estimate")
    calendar = _safe_attr(ticker, "calendar")

    snapshot, history = _extract_eps_history(earnings_dates)
    forward = _extract_forward(earnings_estimate, calendar)

    values: dict[str, ClaimValue | None] = {**snapshot, **forward}
    return values, history


PROVIDERS: dict[str, EarningsProvider] = {
    "yfinance": _fetch_yfinance_earnings,
}


# ── Computed summaries over history ───────────────────────────────────


def _beat_count_over_window(
    surprise_history: list[ClaimHistoryPoint],
    window: int = HISTORY_LIMIT_QUARTERS,
) -> int | None:
    """Count strictly-positive surprises across the last ``window``
    quarters of history. None when no history exists at all (vs. 0
    which means "history exists but no beats")."""
    if not surprise_history:
        return None
    tail = surprise_history[-window:]
    return sum(1 for p in tail if p.value > 0)


def _avg_surprise_over_window(
    surprise_history: list[ClaimHistoryPoint],
    window: int = HISTORY_LIMIT_QUARTERS,
) -> float | None:
    if not surprise_history:
        return None
    tail = surprise_history[-window:]
    if not tail:
        return None
    return sum(p.value for p in tail) / len(tail)


# ── Async entry point ─────────────────────────────────────────────────


async def fetch_earnings(
    symbol: str,
    *,
    provider: str = "yfinance",
) -> dict[str, Claim]:
    """Fetch one symbol's earnings history + forward consensus.

    Single-provider per call: failures propagate. Stable shape — every
    key in ``CLAIM_KEYS`` is present, even when upstream returned no
    history (the corresponding ``Claim.value`` is None and
    ``Claim.history`` is ``[]``).
    """
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    fetch = PROVIDERS[provider]
    target = symbol.upper()
    service_id = f"{provider}.earnings"

    with log_external_call(
        service_id, {"symbol": target, "provider": provider}
    ) as call:
        raw, history_map = await asyncio.to_thread(fetch, target)
        # Compute summary metrics over the history list — single source
        # of truth for "last 20 quarters" math.
        surprise_history = history_map.get("eps_surprise_pct", [])
        raw["last_20q.beat_count"] = _beat_count_over_window(surprise_history)
        raw["last_20q.avg_surprise_pct"] = _avg_surprise_over_window(
            surprise_history
        )
        non_null = sum(1 for k in CLAIM_KEYS if raw.get(k) is not None)
        history_count = sum(1 for k in HISTORY_KEYS if history_map.get(k))
        call.record_output(
            {
                "claim_count": len(CLAIM_KEYS),
                "non_null_count": non_null,
                "history_populated_count": history_count,
            }
        )

    fetched_at = datetime.now(UTC)
    out: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        out[key] = Claim(
            description=_DESCRIPTIONS[key],
            value=raw.get(key),
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail=_DETAILS[key],
            ),
            history=history_map.get(key, []),
        )
    return out
