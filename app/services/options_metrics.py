"""
The figures an IV snapshot stores, computed from a chain (ADR 0008).

The method, which every stored row is tagged with (``METHOD_VERSION``):

- **Usable quote:** a regular contract with a bid, an ask at or above it,
  and a spread within 25% of the mid or $0.05, whichever is wider.
- **Forward:** from put-call parity, F = K + (C − P) / DF, the median over
  the three strikes where call and put are closest in price. It carries
  the dividends and the quote delay. Off by more than 3% from spot carried
  at the rate less the trailing dividend yield, the quotes are stale or
  broken and the forward falls back to that carry (flagged).
- **Smile:** Black-76 IVs from the out-of-the-money side (puts below the
  forward, calls above), where American early exercise is negligible,
  for the strikes within 2.5 ATM standard deviations (at most 25).
- **ATM vol:** linear in ln(K/F) between the two strikes around the forward.
- **IV30 / IV90:** total variance interpolated between the expiries around
  30 (90) days, using only expiries at least 7 days out; a lone expiry
  within 15 (45) days of the target stands in, flagged.
- **Skew:** IV at the 25-delta put strike minus IV at the 25-delta call
  strike, on the expiry nearest 30 days; refused when the strikes don't
  reach either wing or the bracket around it is wider than half an ATM
  standard deviation.
- **Realized vol:** 20 and 60 sessions, completed sessions only.
- **A snapshot needs an IV30.** Rows are never updated, so a row without
  one would be the ticker's permanent figure for the day and the night's
  retry would skip it; without an IV30 the status is ``no_usable_quotes``
  and the retry tries again.
- **Open interest and volume** add up over the expiries read (those
  around 30 and 90 days), not the whole chain.

The detail keeps the raw near-money quotes, so a later method can be
recomputed over the whole history.

Versions: 1, from 2026-11-13; 2, from 2026-11-16, measures time to expiry
to a half day's 1 pm close and quotes taken after it from 1 pm
(``market_calendar.early_closes``). Version 1 ran every session to 16:00.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.services import market_calendar as mc
from app.services import options_math as om
from app.services.options_chain import ChainFetch, ExpiryQuotes, Quote

METHOD_VERSION = 2

MAX_SPREAD_SHARE = 0.25
MIN_SPREAD = 0.05
FORWARD_STRIKES = 3
FORWARD_TOLERANCE = 0.03
MONEYNESS_SIGMAS = 2.5
MAX_STRIKES = 25
MIN_SNAPSHOT_DAYS = 7
CONSTANT_MATURITIES = ((30, 15), (90, 45))  # (target days, one-sided reach in days)
SKEW_DELTA = 0.25
SKEW_MAX_GAP_SIGMAS = 0.5
RV_WINDOWS = (20, 60)
_DAYS_PER_YEAR = 365
_DETAIL_DIGITS = 4


def usable(quote: Quote) -> bool:
    if not quote.regular or quote.bid <= 0 or quote.ask < quote.bid:
        return False
    return quote.ask - quote.bid <= max(MAX_SPREAD_SHARE * quote.mid, MIN_SPREAD)


@dataclass(frozen=True)
class Smile:
    expiry: date
    years: float
    forward: float
    forward_from_parity: bool
    discount: float
    atm_vol: float
    points: tuple[tuple[float, float], ...]  # (strike, IV), ascending strike
    quotes: tuple[tuple[float, ...], ...]  # raw near-money rows for the detail

    @property
    def days(self) -> float:
        return self.years * _DAYS_PER_YEAR


def _forward(
    chain: ExpiryQuotes, spot: float, years: float, rate: float, dividend_yield: float, discount: float
) -> tuple[float, bool] | None:
    calls = {q.strike: q for q in chain.calls if usable(q)}
    puts = {q.strike: q for q in chain.puts if usable(q)}
    closest = sorted((abs(calls[k].mid - puts[k].mid), k) for k in calls.keys() & puts.keys())
    estimates = [k + (calls[k].mid - puts[k].mid) / discount for _gap, k in closest[:FORWARD_STRIKES]]
    parity = statistics.median(estimates) if estimates else None
    if spot <= 0:
        return (parity, True) if parity else None
    carry = spot * math.exp((rate - dividend_yield) * years)
    if parity and abs(parity / carry - 1) <= FORWARD_TOLERANCE:
        return parity, True
    return carry, False


def _raw_rows(chain: ExpiryQuotes, strikes: Iterable[float]) -> tuple[tuple[float, ...], ...]:
    calls = {q.strike: q for q in chain.calls}
    puts = {q.strike: q for q in chain.puts}
    empty = Quote(0.0, 0.0, 0.0, 0, 0, True)
    rows = []
    for k in sorted(strikes):
        c, p = calls.get(k, empty), puts.get(k, empty)
        rows.append((k, c.bid, c.ask, p.bid, p.ask, c.open_interest, p.open_interest, c.volume, p.volume))
    return tuple(rows)


def smile(
    chain: ExpiryQuotes, spot: float, quoted_at: datetime, rate: float, dividend_yield: float
) -> Smile | None:
    """The chain's out-of-the-money IVs near the money, or None when there
    is no usable quote on both sides of the forward."""
    years = mc.years_to_expiry(quoted_at, chain.expiry)
    if years <= 0:
        return None
    discount = math.exp(-rate * years)
    found = _forward(chain, spot, years, rate, dividend_yield, discount)
    if found is None:
        return None
    forward, from_parity = found
    otm = [(q, False) for q in chain.puts if usable(q) and q.strike < forward]
    otm += [(q, True) for q in chain.calls if usable(q) and q.strike >= forward]

    def vol(q: Quote, call: bool) -> float | None:
        return om.implied_vol(q.mid, forward, q.strike, years, discount, call=call)

    below = max((q for q, call in otm if not call), key=lambda q: q.strike, default=None)
    above = min((q for q, call in otm if call), key=lambda q: q.strike, default=None)
    if below is None or above is None:
        return None
    v_below, v_above = vol(below, False), vol(above, True)
    if v_below is None or v_above is None:
        return None
    atm = om.interpolate(
        0.0, [math.log(below.strike / forward), math.log(above.strike / forward)], [v_below, v_above]
    )
    if atm is None:
        return None
    reach = MONEYNESS_SIGMAS * atm * math.sqrt(years)
    near = _spread_across(
        [(math.log(q.strike / forward), q, call) for q, call in otm if abs(math.log(q.strike / forward)) <= reach],
        reach,
        keep={below.strike, above.strike},
    )
    known = {below.strike: v_below, above.strike: v_above}
    points = []
    for _x, q, call in near:
        v = known.get(q.strike) or vol(q, call)
        if v is not None:
            points.append((q.strike, v))
    return Smile(
        expiry=chain.expiry,
        years=years,
        forward=forward,
        forward_from_parity=from_parity,
        discount=discount,
        atm_vol=atm,
        points=tuple(sorted(points)),
        quotes=_raw_rows(chain, {q.strike for _x, q, _c in near}),
    )


def _spread_across(
    candidates: list[tuple[float, Quote, bool]], reach: float, *, keep: set[float]
) -> list[tuple[float, Quote, bool]]:
    """At most ``MAX_STRIKES`` of the (ln(K/F), quote, call) candidates,
    spread evenly over [-reach, reach] rather than the nearest ones: a
    chain with a strike every dollar would otherwise never reach the
    25-delta wings. The strikes around the forward are always kept."""
    if len(candidates) <= MAX_STRIKES:
        return sorted(candidates, key=lambda c: c[0])
    chosen = {c[1].strike: c for c in candidates if c[1].strike in keep}
    slots = MAX_STRIKES - len(chosen)
    for i in range(slots):
        target = -reach + 2 * reach * i / (slots - 1)
        best = min(candidates, key=lambda c: abs(c[0] - target))
        chosen.setdefault(best[1].strike, best)
    return sorted(chosen.values(), key=lambda c: c[0])


def snapshot_expiries(listed: tuple[date, ...], quoted_at: datetime) -> list[date]:
    """The expiries around 30 and 90 days, at least a week out (at most 4)."""
    days = [(d, mc.years_to_expiry(quoted_at, d) * _DAYS_PER_YEAR) for d in listed]
    eligible = [(d, t) for d, t in days if t >= MIN_SNAPSHOT_DAYS]
    picked: set[date] = set()
    for target, _reach in CONSTANT_MATURITIES:
        below = [d for d, t in eligible if t <= target]
        above = [d for d, t in eligible if t >= target]
        picked.update(below[-1:] + above[:1])
    return sorted(picked)


def skew_25d(s: Smile) -> float | None:
    """IV at the 25-delta put strike minus IV at the 25-delta call strike."""
    if len(s.points) < 2:
        return None
    xs = [math.log(k) for k, _v in s.points]
    ys = [v for _k, v in s.points]
    max_gap = SKEW_MAX_GAP_SIGMAS * s.atm_vol * math.sqrt(s.years)

    def wing(call: bool) -> float | None:
        x = math.log(om.delta_strike(s.forward, s.atm_vol, s.years, call=call, delta=SKEW_DELTA))
        value = om.interpolate(x, xs, ys)
        if value is None:
            return None
        i = next(i for i, xi in enumerate(xs) if xi >= x)
        return value if i == 0 or xs[i] - xs[i - 1] <= max_gap else None

    put, call = wing(False), wing(True)
    return None if put is None or call is None else put - call


@dataclass(frozen=True)
class SnapshotMetrics:
    status: str  # "ok" (an IV30 exists) or "no_usable_quotes"
    iv30: float | None
    iv30_extrapolated: bool
    iv90: float | None
    iv90_extrapolated: bool
    skew25: float | None
    rv20: float | None
    rv60: float | None
    call_open_interest: int
    put_open_interest: int
    call_volume: int
    put_volume: int
    detail: dict[str, Any]


def _completed_closes(fetched: ChainFetch, quoted_at: datetime) -> list[float]:
    """Closes of sessions finished by the quote time."""
    today = quoted_at.astimezone(mc.ET).date()
    finished = quoted_at >= mc.session_close(today)
    return [c for d, c in fetched.closes if d < today or (d == today and finished)]


def _round(value: float) -> float:
    return round(value, _DETAIL_DIGITS)


def _detail(smiles: list[Smile], quoted_at: datetime, rate: float, rate_assumed: bool) -> dict[str, Any]:
    return {
        "method_version": METHOD_VERSION,
        "quoted_at": quoted_at.isoformat(),
        "rate": _round(rate),
        "rate_assumed": rate_assumed,
        "expiries": [
            {
                "expiry": s.expiry.isoformat(),
                "years": round(s.years, 6),
                "sessions": mc.sessions_between(quoted_at.astimezone(mc.ET).date(), s.expiry),
                "forward": _round(s.forward),
                "forward_from_parity": s.forward_from_parity,
                "atm_vol": _round(s.atm_vol),
                "smile": [[_round(k), _round(v)] for k, v in s.points],
                # strike, call bid/ask, put bid/ask, call/put OI, call/put volume
                "quotes": [[_round(x) for x in row] for row in s.quotes],
            }
            for s in smiles
        ],
    }


def chain_smiles(fetched: ChainFetch, quoted_at: datetime, rate: float) -> list[Smile]:
    """The smile of each fetched expiry that has one, in expiry order."""
    found = (smile(fetched.chains[d], fetched.spot, quoted_at, rate, fetched.dividend_yield) for d in sorted(fetched.chains))
    return [s for s in found if s is not None]


def snapshot_metrics(
    fetched: ChainFetch,
    quoted_at: datetime,
    rate: float,
    *,
    rate_assumed: bool = False,
    smiles: list[Smile] | None = None,
) -> SnapshotMetrics:
    """``smiles`` when the caller already has them (the page); else computed."""
    smiles = chain_smiles(fetched, quoted_at, rate) if smiles is None else smiles
    eligible = [s for s in smiles if s.days >= MIN_SNAPSHOT_DAYS]
    points = [(s.years, s.atm_vol) for s in eligible]
    (iv30, ex30), (iv90, ex90) = (
        om.constant_maturity_vol(points, target / _DAYS_PER_YEAR, max_extrapolation=reach / _DAYS_PER_YEAR)
        for target, reach in CONSTANT_MATURITIES
    )
    nearest = min(eligible, key=lambda s: abs(s.days - CONSTANT_MATURITIES[0][0]), default=None)
    closes = _completed_closes(fetched, quoted_at)
    rv20, rv60 = (om.realized_vol(closes, n) for n in RV_WINDOWS)
    calls = [q for chain in fetched.chains.values() for q in chain.calls]
    puts = [q for chain in fetched.chains.values() for q in chain.puts]
    return SnapshotMetrics(
        status="ok" if iv30 is not None else "no_usable_quotes",
        iv30=iv30,
        iv30_extrapolated=ex30,
        iv90=iv90,
        iv90_extrapolated=ex90,
        skew25=skew_25d(nearest) if nearest else None,
        rv20=rv20,
        rv60=rv60,
        call_open_interest=sum(q.open_interest for q in calls),
        put_open_interest=sum(q.open_interest for q in puts),
        call_volume=sum(q.volume for q in calls),
        put_volume=sum(q.volume for q in puts),
        detail=_detail(smiles, quoted_at, rate, rate_assumed),
    )
