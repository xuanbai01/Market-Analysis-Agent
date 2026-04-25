"""
Earnings tool. Returns last-4-quarters EPS history + forward consensus
+ a couple of summary stats (beat count, average surprise) as a flat
``dict[str, Claim]``.

Why yfinance only for v1: ``Ticker.earnings_dates`` returns a clean
DataFrame with EPS estimate, reported EPS, and surprise % per period
in a single round trip. ``Ticker.earnings_estimate`` covers the
forward consensus. ``Ticker.calendar`` gives the next reporting date.
Three attributes, all structured, ~1 HTTP call equivalent. The agent
gets enough analyst-shaped signal ("they beat, by how much, three of
the last four quarters") to compose an Earnings section without
parsing prose.

Why transcripts are *not* in this PR: Motley Fool / Investor.com /
Seeking Alpha transcript scrapers are exactly the "fragile, breaks at
the worst time" surface ADR 0003's risk table flags. Better to ship a
stable v1 with structured numbers and add transcripts behind an
``include_transcript=True`` flag in a follow-up — once we know what
claims the agent actually needs from a transcript (management tone,
guidance change keywords, or just "did they raise guidance"). The
schema remains stable; transcripts add new keys, never replace
existing ones.

Why no 8-K text fetch via fetch_edgar: 8-K earnings releases are
unstructured prose. The numbers are already in earnings_dates;
extracting commentary from 8-K text is parse_filing's job, not this
tool's.

Why no persistence: earnings actuals for past quarters are settled and
won't change, but the next-quarter estimate moves as analysts revise.
For an on-demand research tool, fresh fetches are cheap and avoid the
"stale forward estimate" failure mode. Cache layer is a follow-up if
volume justifies it.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.observability import log_external_call
from app.schemas.research import Claim, ClaimValue, Source

# ── Stable claim contract ─────────────────────────────────────────────
# 4 metrics × 4 past quarters + 3 forward + 2 computed = 21 keys.
# Order is for deterministic iteration; agents read by key, not position.
_PAST_QUARTERS: tuple[str, ...] = ("q1", "q2", "q3", "q4")
_PER_QUARTER_METRICS: tuple[str, ...] = (
    "report_date",
    "eps_actual",
    "eps_estimate",
    "eps_surprise_pct",
)
_FORWARD_KEYS: tuple[str, ...] = (
    "next.report_date",
    "next.eps_estimate",
    "next.revenue_estimate",
)
_COMPUTED_KEYS: tuple[str, ...] = (
    "last_4q.beat_count",
    "last_4q.avg_surprise_pct",
)


def _build_claim_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for q in _PAST_QUARTERS:
        for metric in _PER_QUARTER_METRICS:
            keys.append(f"{q}.{metric}")
    keys.extend(_FORWARD_KEYS)
    keys.extend(_COMPUTED_KEYS)
    return tuple(keys)


CLAIM_KEYS: tuple[str, ...] = _build_claim_keys()


_DESCRIPTIONS: dict[str, str] = {
    "report_date": "Earnings report date",
    "eps_actual": "Reported EPS",
    "eps_estimate": "Consensus EPS estimate",
    "eps_surprise_pct": "EPS surprise (%)",
    "next.report_date": "Next earnings report date (expected)",
    "next.eps_estimate": "Next quarter consensus EPS estimate",
    "next.revenue_estimate": "Next quarter consensus revenue estimate",
    "last_4q.beat_count": "Number of EPS beats over the last 4 quarters",
    "last_4q.avg_surprise_pct": "Average EPS surprise (%) over the last 4 quarters",
}

_DETAILS: dict[str, str] = {
    "report_date": "earnings_dates index",
    "eps_actual": "earnings_dates[Reported EPS]",
    "eps_estimate": "earnings_dates[EPS Estimate]",
    "eps_surprise_pct": "earnings_dates[Surprise(%)]",
    "next.report_date": "calendar[Earnings Date]",
    "next.eps_estimate": "earnings_estimate[+1q].avg",
    "next.revenue_estimate": "earnings_estimate[+1q].revenueAvg",
    "last_4q.beat_count": "computed: count of past 4Q with surprise > 0",
    "last_4q.avg_surprise_pct": "computed: mean of past 4Q non-null surprises",
}


def _description_for(key: str) -> str:
    """Per-key description, with the per-quarter metrics generating their label."""
    if key in _DESCRIPTIONS:
        return _DESCRIPTIONS[key]
    # Per-quarter key like "q1.eps_actual" — split and look up by metric.
    quarter, _, metric = key.partition(".")
    base = _DESCRIPTIONS[metric]
    # q1 is "most recent" not "first" — make that legible in the description.
    quarter_label = {"q1": "most recent", "q2": "Q-2", "q3": "Q-3", "q4": "Q-4"}[quarter]
    return f"{base} ({quarter_label})"


def _detail_for(key: str) -> str:
    if key in _DETAILS:
        return _DETAILS[key]
    _, _, metric = key.partition(".")
    return _DETAILS[metric]


# Provider signature: (symbol) -> {claim_key: value | None}. Sync —
# yfinance is blocking; the async entry point hands it to ``to_thread``.
EarningsProvider = Callable[[str], dict[str, ClaimValue | None]]


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


def _extract_past_quarters(earnings_dates: Any) -> dict[str, ClaimValue | None]:
    """
    Pull the 4 most recent past quarters from yfinance's earnings_dates.

    Past = ``Reported EPS`` is a real number (yfinance fills NaN for
    future periods even though they share the same DataFrame). Sorted
    by index date descending, q1 = newest.
    """
    out: dict[str, ClaimValue | None] = {}
    if earnings_dates is None or getattr(earnings_dates, "empty", True):
        return out

    import pandas as pd  # noqa: PLC0415

    # Normalize: rows with a real Reported EPS are past quarters. yfinance
    # fills future rows with NaN for Reported EPS / Surprise(%).
    if "Reported EPS" not in earnings_dates.columns:
        return out

    past_mask = earnings_dates["Reported EPS"].apply(lambda v: not pd.isna(v))
    past = earnings_dates[past_mask].copy()
    if past.empty:
        return out

    # Newest first.
    past = past.sort_index(ascending=False)
    past = past.head(len(_PAST_QUARTERS))

    has_surprise_col = "Surprise(%)" in past.columns

    for i, (idx, row) in enumerate(past.iterrows()):
        quarter = _PAST_QUARTERS[i]
        # ``idx`` is a tz-aware Timestamp; format as ISO date string.
        try:
            date_str = idx.date().isoformat()
        except AttributeError:
            date_str = str(idx)
        out[f"{quarter}.report_date"] = date_str
        out[f"{quarter}.eps_actual"] = _safe_float(row.get("Reported EPS"))
        out[f"{quarter}.eps_estimate"] = _safe_float(row.get("EPS Estimate"))

        # Use yfinance's Surprise(%) when available, else derive.
        surprise: float | None = None
        if has_surprise_col:
            surprise = _safe_float(row.get("Surprise(%)"))
        if surprise is None:
            actual = _safe_float(row.get("Reported EPS"))
            estimate = _safe_float(row.get("EPS Estimate"))
            if actual is not None and estimate not in (None, 0):
                surprise = (actual - estimate) / abs(estimate) * 100.0
        out[f"{quarter}.eps_surprise_pct"] = surprise

    return out


def _extract_forward(
    earnings_estimate: Any, calendar: Any
) -> dict[str, ClaimValue | None]:
    """Forward EPS + revenue from earnings_estimate; expected date from calendar."""
    out: dict[str, ClaimValue | None] = {}

    # Next-quarter EPS / revenue estimate. yfinance.earnings_estimate is
    # indexed by period label ('0q', '+1q', '0y', '+1y'); '+1q' is the
    # next reporting quarter.
    if (
        earnings_estimate is not None
        and not getattr(earnings_estimate, "empty", True)
        and "+1q" in getattr(earnings_estimate, "index", [])
    ):
        row = earnings_estimate.loc["+1q"]
        out["next.eps_estimate"] = _safe_float(row.get("avg"))
        out["next.revenue_estimate"] = _safe_float(row.get("revenueAvg"))

    # Next reporting date from calendar dict. yfinance returns either a
    # list of dates or a single date depending on version; handle both.
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


def _fetch_yfinance_earnings(symbol: str) -> dict[str, ClaimValue | None]:
    """Pull earnings_dates + earnings_estimate + calendar from yfinance once."""
    import yfinance  # noqa: PLC0415

    ticker = yfinance.Ticker(symbol)
    earnings_dates = _safe_attr(ticker, "earnings_dates")
    earnings_estimate = _safe_attr(ticker, "earnings_estimate")
    calendar = _safe_attr(ticker, "calendar")

    raw: dict[str, ClaimValue | None] = {}
    raw.update(_extract_past_quarters(earnings_dates))
    raw.update(_extract_forward(earnings_estimate, calendar))
    return raw


PROVIDERS: dict[str, EarningsProvider] = {
    "yfinance": _fetch_yfinance_earnings,
}


# ── Computed metrics ──────────────────────────────────────────────────


def _beat_count(raw: dict[str, ClaimValue | None]) -> int | None:
    """Count strictly-positive surprises across the 4 past quarters.

    Returns None when no past quarter has a surprise — distinguishes
    "we know about 0 beats out of 4" from "we don't have any data".
    """
    surprises = [raw.get(f"{q}.eps_surprise_pct") for q in _PAST_QUARTERS]
    non_null = [s for s in surprises if isinstance(s, int | float)]
    if not non_null:
        return None
    return sum(1 for s in non_null if s > 0)


def _avg_surprise_pct(raw: dict[str, ClaimValue | None]) -> float | None:
    surprises = [raw.get(f"{q}.eps_surprise_pct") for q in _PAST_QUARTERS]
    non_null = [float(s) for s in surprises if isinstance(s, int | float)]
    if not non_null:
        return None
    return sum(non_null) / len(non_null)


# ── Async entry point ─────────────────────────────────────────────────


async def fetch_earnings(
    symbol: str,
    *,
    provider: str = "yfinance",
) -> dict[str, Claim]:
    """
    Fetch one symbol's earnings history + forward consensus.

    Single-provider per call: failures propagate. Stable shape — every
    key in ``CLAIM_KEYS`` is present, even when upstream returned only
    partial history (the corresponding ``Claim.value`` is None).
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
        raw = await asyncio.to_thread(fetch, target)
        # Layer computed metrics on top of provider output.
        raw["last_4q.beat_count"] = _beat_count(raw)
        raw["last_4q.avg_surprise_pct"] = _avg_surprise_pct(raw)
        non_null = sum(1 for k in CLAIM_KEYS if raw.get(k) is not None)
        call.record_output(
            {"claim_count": len(CLAIM_KEYS), "non_null_count": non_null}
        )

    fetched_at = datetime.now(UTC)
    out: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        out[key] = Claim(
            description=_description_for(key),
            value=raw.get(key),
            source=Source(
                tool=service_id,
                fetched_at=fetched_at,
                detail=_detail_for(key),
            ),
        )
    return out
