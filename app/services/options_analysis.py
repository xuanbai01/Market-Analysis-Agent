"""
The options page's figures (ADR 0008), from fetched chains and their
smiles (``options_metrics``). Pure functions; the service in
``options_report`` fetches and assembles.

- **Expiries read:** the first listed, the ones nearest 7, 14, 30, 45, 60,
  90, 180 and 365 days, the snapshot's (around 30 and 90 days, so today's
  IV30 is computed as the stored ones were), and for a stock with a report coming, the two
  before its reaction session and the two after (within 60 days), which
  the implied earnings move needs.
- **Expected move:** one standard deviation of the log price to each
  expiry, IV·√T, drawn as forward·e^(±IV·√T); the ATM straddle beside it.
- **Chain table:** strikes within 2.5 ATM standard deviations (at most
  30); each side's IV from its own mid, deltas from the smile's IV.
- **Open interest by strike:** within 3 standard deviations.
- **IV history:** the stored daily IV30s (ADR 0008). Today's live IV30 is
  ranked against them: a percentile from 63 sessions (one earnings cycle),
  an IV rank (where it sits between the low and the high) from 126, both
  over the last 252.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from app.schemas.options import (
    ChainRow,
    EarningsBlock,
    ExpiryChain,
    ExpirySummary,
    IvHistory,
    IvHistoryPoint,
    OpenInterestPoint,
    PastMove,
    SmilePoint,
)
from app.schemas.research import Claim, ClaimUnit, Source
from app.services import market_calendar as mc
from app.services import options_math as om
from app.services.earnings_calendar import Schedule, reaction_sessions
from app.services.options_chain import ExpiryQuotes, Quote
from app.services.options_earnings import MAX_EVENT_DAYS, EventMove
from app.services.options_metrics import (
    MIN_SNAPSHOT_DAYS,
    MONEYNESS_SIGMAS,
    Smile,
    snapshot_expiries,
    usable,
)

REPORT_TARGET_DAYS = (7, 14, 30, 45, 60, 90, 180, 365)
EARNINGS_BRACKET = 2
DEFAULT_TARGET_DAYS = 30
MAX_ROWS = 30
OPEN_INTEREST_SIGMAS = 3.0
PERCENTILE_MIN_SESSIONS = 63
RANK_MIN_SESSIONS = 126
HISTORY_WINDOW = 252
_YEAR_DAYS = 365
_CLAIM_TOOL = "computed.options"


def _days(quoted_at: datetime, expiry: date) -> float:
    return mc.years_to_expiry(quoted_at, expiry) * _YEAR_DAYS


def report_expiries(
    listed: tuple[date, ...], quoted_at: datetime, reaction: tuple[date, date] | None
) -> list[date]:
    if not listed:
        return []
    # The snapshot's expiries too: today's IV30 is then the history's IV30.
    picked = {listed[0], *snapshot_expiries(listed, quoted_at)}
    for target in REPORT_TARGET_DAYS:
        picked.add(min(listed, key=lambda d: abs(_days(quoted_at, d) - target)))
    if reaction is not None:
        first, last = reaction
        before = [d for d in listed if d < first]
        after = [d for d in listed if d >= last and _days(quoted_at, d) <= MAX_EVENT_DAYS]
        picked.update(before[-EARNINGS_BRACKET:] + after[:EARNINGS_BRACKET])
    return sorted(picked)


def _totals(chain: ExpiryQuotes) -> tuple[int, int, int, int]:
    return (
        sum(q.open_interest for q in chain.calls),
        sum(q.open_interest for q in chain.puts),
        sum(q.volume for q in chain.calls),
        sum(q.volume for q in chain.puts),
    )


def expiry_summary(
    chain: ExpiryQuotes, s: Smile, reaction: tuple[date, date] | None, quoted_at: datetime
) -> ExpirySummary:
    spread = s.atm_vol * math.sqrt(s.years)
    calls = {q.strike: q for q in chain.calls if usable(q)}
    puts = {q.strike: q for q in chain.puts if usable(q)}
    strike = min(calls.keys() & puts.keys(), key=lambda k: abs(k - s.forward), default=None)
    call_oi, put_oi, call_vol, put_vol = _totals(chain)
    return ExpirySummary(
        expiry=s.expiry,
        days=s.days,
        sessions=mc.sessions_between(quoted_at.astimezone(mc.ET).date(), s.expiry),
        forward=s.forward,
        forward_from_parity=s.forward_from_parity,
        atm_iv=s.atm_vol,
        expected_move=spread,
        low=s.forward * math.exp(-spread),
        high=s.forward * math.exp(spread),
        straddle=calls[strike].mid + puts[strike].mid if strike is not None else None,
        straddle_strike=strike,
        call_open_interest=call_oi,
        put_open_interest=put_oi,
        call_volume=call_vol,
        put_volume=put_vol,
        includes_earnings=reaction is not None and s.expiry >= reaction[1],
    )


def default_smile(smiles: Sequence[Smile]) -> Smile | None:
    """The expiry nearest 30 days, at least a week out when there is one."""
    eligible = [s for s in smiles if s.days >= MIN_SNAPSHOT_DAYS] or list(smiles)
    return min(eligible, key=lambda s: abs(s.days - DEFAULT_TARGET_DAYS), default=None)


def _side_iv(q: Quote | None, s: Smile, call: bool) -> float | None:
    if q is None or not usable(q):
        return None
    return om.implied_vol(q.mid, s.forward, q.strike, s.years, s.discount, call=call)


def _call_delta(s: Smile, strike: float, vol: float | None) -> float | None:
    if not vol:
        return None
    d1 = (math.log(s.forward / strike) + vol * vol * s.years / 2) / (vol * math.sqrt(s.years))
    return om.norm_cdf(d1)


def expiry_chain(chain: ExpiryQuotes, s: Smile) -> ExpiryChain:
    sigma_t = s.atm_vol * math.sqrt(s.years)
    calls = {q.strike: q for q in chain.calls}
    puts = {q.strike: q for q in chain.puts}
    strikes = sorted(calls.keys() | puts.keys())
    near = sorted(
        sorted((k for k in strikes if abs(math.log(k / s.forward)) <= MONEYNESS_SIGMAS * sigma_t),
               key=lambda k: abs(math.log(k / s.forward)))[:MAX_ROWS]
    )
    smile_iv = dict(s.points)
    empty = Quote(0.0, 0.0, 0.0, 0, 0, False)
    rows = []
    for k in near:
        c, p = calls.get(k), puts.get(k)
        call_iv, put_iv = _side_iv(c, s, True), _side_iv(p, s, False)
        delta = _call_delta(s, k, smile_iv.get(k) or call_iv or put_iv)
        c, p = c or empty, p or empty
        rows.append(ChainRow(
            strike=k,
            call_bid=c.bid, call_ask=c.ask, call_iv=call_iv, call_delta=delta,
            call_open_interest=c.open_interest, call_volume=c.volume, call_usable=usable(c),
            put_bid=p.bid, put_ask=p.ask, put_iv=put_iv, put_delta=None if delta is None else delta - 1,
            put_open_interest=p.open_interest, put_volume=p.volume, put_usable=usable(p),
        ))
    open_interest = [
        OpenInterestPoint(strike=k, call=(calls.get(k) or empty).open_interest, put=(puts.get(k) or empty).open_interest)
        for k in strikes
        if abs(math.log(k / s.forward)) <= OPEN_INTEREST_SIGMAS * sigma_t
        and ((calls.get(k) or empty).open_interest or (puts.get(k) or empty).open_interest)
    ]
    return ExpiryChain(
        expiry=s.expiry,
        days=s.days,
        forward=s.forward,
        atm_iv=s.atm_vol,
        smile=[
            SmilePoint(strike=k, log_moneyness=math.log(k / s.forward), iv=v, side="put" if k < s.forward else "call")
            for k, v in s.points
        ],
        rows=rows,
        open_interest=open_interest,
    )


def put_call_ratios(chains: Iterable[ExpiryQuotes]) -> tuple[float | None, float | None]:
    """(put ÷ call open interest, put ÷ call volume) over the expiries read."""
    call_oi = put_oi = call_vol = put_vol = 0
    for chain in chains:
        c_oi, p_oi, c_vol, p_vol = _totals(chain)
        call_oi, put_oi, call_vol, put_vol = call_oi + c_oi, put_oi + p_oi, call_vol + c_vol, put_vol + p_vol
    return (put_oi / call_oi if call_oi else None, put_vol / call_vol if call_vol else None)


def iv_history(points: Sequence[tuple[date, float]], current: float | None) -> IvHistory:
    recent = [v for _d, v in points][-HISTORY_WINDOW:]
    percentile = rank = None
    if current is not None and len(points) >= PERCENTILE_MIN_SESSIONS:
        percentile = 100 * sum(1 for v in recent if v <= current) / len(recent)
    if current is not None and len(points) >= RANK_MIN_SESSIONS:
        low, high = min(recent), max(recent)
        if high > low:
            rank = min(max(100 * (current - low) / (high - low), 0.0), 100.0)
    return IvHistory(
        points=[IvHistoryPoint(date=d, iv30=v) for d, v in points[-HISTORY_WINDOW:]],
        sessions=len(points),
        since=points[0][0] if points else None,
        percentile=percentile,
        rank=rank,
    )


def earnings_block(
    schedule: Schedule | None, event: EventMove, past: list[PastMove], spot: float | None, *, estimated: bool
) -> EarningsBlock | None:
    """None for a fund (no schedule)."""
    if schedule is None:
        return None
    nxt = schedule.next
    reaction = reaction_sessions(nxt.when.date(), nxt.timing) if nxt else None
    return EarningsBlock(
        next_date=nxt.when.date() if nxt else None,
        next_timing=nxt.timing if nxt else None,
        estimated=estimated,
        reaction_date=reaction[1] if reaction else None,
        implied_move=event.implied_move,
        implied_move_usd=spot * event.implied_move if spot and event.implied_move is not None else None,
        event_sigma=event.event_sigma,
        base_vol=event.base_vol,
        method=event.method,  # type: ignore[arg-type]
        refused=event.refused,
        expiries=list(event.expiries),
        past=past,
        past_mean_abs=sum(abs(m.move) for m in past) / len(past) if past else None,
    )


# Comparison claims say which way they go, in words code picks (ADR 0007):
# the read copies the words instead of reading a sign. Keyed by the
# direction at display precision (+1, −1, 0).
_VS_REALIZED = {
    1: "IV30 above realized volatility (20 sessions): options price more movement than the stock has shown",
    -1: "IV30 below realized volatility (20 sessions): options price less movement than the stock has shown",
    0: "IV30 level with realized volatility (20 sessions): options price as much movement as the stock has shown",
}
_TERM = {
    1: "IV90 above IV30: the term structure slopes up, longer expiries price more volatility",
    -1: "IV90 below IV30: the term structure slopes down, longer expiries price less volatility",
    0: "IV90 level with IV30: the term structure is flat",
}
_SKEW = {
    1: "25-delta skew, expiry nearest 30 days: puts carry higher IV than calls",
    -1: "25-delta skew, expiry nearest 30 days: calls carry higher IV than puts",
    0: "25-delta skew, expiry nearest 30 days: puts and calls carry the same IV",
}
_PUT_CALL = {
    1: "Put/call open interest, expiries read: more puts open than calls",
    -1: "Put/call open interest, expiries read: more calls open than puts",
    0: "Put/call open interest, expiries read: as many puts open as calls",
}
_EARNINGS_WAY = {1: "above", -1: "below", 0: "level with"}


def _direction(x: float, places: int) -> int:
    """The sign of ``x`` as displayed: 0 when it rounds to zero."""
    shown = round(x, places)
    return (shown > 0) - (shown < 0)


def _gap(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def claims(
    *,
    iv30: float | None,
    iv90: float | None,
    rv20: float | None,
    rv60: float | None,
    skew25: float | None,
    default: ExpirySummary | None,
    put_call_oi: float | None,
    earnings: EarningsBlock | None,
    history: IvHistory,
    at: datetime,
) -> list[Claim]:
    """The headline figures and comparisons as claims (unit and source
    each), the facts the page's cited read is written from."""
    points = 4  # percentage points show two decimals: a fraction to 4 places
    iv_gap, term = _gap(iv30, rv20), _gap(iv90, iv30)
    rows: list[tuple[str, float | str | None, ClaimUnit, str]] = [
        ("Implied volatility, 30 days (IV30)", iv30, "fraction", "total variance between the expiries around 30 days"),
        ("Implied volatility, 90 days (IV90)", iv90, "fraction", "total variance between the expiries around 90 days"),
        ("Realized volatility, 20 sessions", rv20, "fraction", "close-to-close, zero mean, ×252"),
        ("Realized volatility, 60 sessions", rv60, "fraction", "close-to-close, zero mean, ×252"),
        (_VS_REALIZED[_direction(iv_gap or 0.0, points)], iv_gap, "percentage_points", "IV30 − RV20"),
        (_TERM[_direction(term or 0.0, points)], term, "percentage_points", "IV90 − IV30"),
        (_SKEW[_direction(skew25 or 0.0, points)], skew25, "percentage_points",
         "IV at the 25-delta put strike − IV at the 25-delta call strike"),
        (_PUT_CALL[_direction((put_call_oi or 1.0) - 1.0, 2)], put_call_oi, "ratio", "Σ put OI ÷ Σ call OI"),
    ]
    if default is not None:
        rows.append((f"Expected move to {default.expiry.isoformat()} (one standard deviation)",
                     default.expected_move, "fraction", "ATM IV × √T"))
    if earnings is not None and earnings.next_date is not None:
        report_on = earnings.next_date.isoformat()
        rows.append((f"Implied earnings move, report on {report_on} (expected absolute move)",
                     earnings.implied_move, "fraction", "√(2/π) × the report's σ, from the expiries around it"))
        if earnings.implied_move is None and earnings.refused:
            # Said, so the read doesn't stand another figure in for it.
            rows.append((f"Implied earnings move, report on {report_on}: not priced", earnings.refused, "string",
                         "why the expiries can't separate the report from other days"))
    if earnings is not None and earnings.past:
        n = len(earnings.past)
        rows.append((f"Average absolute move after the last {n} reports",
                     earnings.past_mean_abs, "fraction", "mean |ln(close after ÷ close before)|"))
        priced_gap = _gap(earnings.implied_move, earnings.past_mean_abs)
        if priced_gap is not None:
            way = _EARNINGS_WAY[_direction(priced_gap, points)]
            rows.append((f"Implied earnings move {way} the average move after the last {n} report{'s' if n > 1 else ''}",
                         priced_gap, "percentage_points", "implied earnings move − average absolute move"))
    if history.percentile is not None:
        rows.append((f"IV30 percentile over {min(history.sessions, HISTORY_WINDOW)} stored sessions",
                     history.percentile, "percent", "share of stored daily IV30s at or below today's"))
    return [
        Claim(description=name, value=value, unit=unit, source=Source(tool=_CLAIM_TOOL, fetched_at=at, detail=detail))
        for name, value, unit, detail in rows
        if value is not None
    ]
