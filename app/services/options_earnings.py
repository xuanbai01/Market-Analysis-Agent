"""
The earnings move the options price, and the moves past reports made
(ADR 0008).

**Implied move.** Total variance to an expiry is modelled as a per-session
variance ``v`` on every session plus the report's own variance ``σe²`` on
expiries that include the reaction session: w = v·n + σe²·[includes it],
with n the NYSE sessions to the expiry (weekends carry no variance).

- *Before and after:* the last expiry before the reaction (at least three
  sessions out; shorter ones are too noisy) gives v = w1 / n1, and the first
  expiry that includes it gives σe² = w2 − v·n2.
- *Two after:* with no usable expiry before, the first two expiries that
  include the reaction (at least three sessions apart) give
  v = (w3 − w2) / (n3 − n2) and σe² = w2 − v·n2.

The page shows the expected absolute move, √(2/π)·σe (≈ 0.80σe), which is
what the average of past absolute moves compares with. It's refused, with
the reason, when there is no report date, when the first expiry including
the report is more than 60 days out (its straddle mostly prices other
days), when a date Yahoo marks as an estimate sits within two sessions of
an expiry used, or when the variances leave nothing (or less) for the report.

**Past moves.** The log return across each report's reaction: the close
before it to the close of the reaction session (a report before the open
or during a session reacts that day, after the close the next session).
At an unknown time it spans the session before to the session after, and
says so.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.schemas.options import PastMove
from app.services import market_calendar as mc
from app.services import options_math as om
from app.services.earnings_calendar import Announcement, reaction_sessions
from app.services.options_metrics import Smile

EXPECTED_ABS = math.sqrt(2 / math.pi)
MIN_SESSIONS = 3
MAX_EVENT_DAYS = 60
ESTIMATE_GUARD_SESSIONS = 2
PAST_LIMIT = 8


@dataclass(frozen=True)
class EventMove:
    event_sigma: float | None
    implied_move: float | None
    base_vol: float | None
    method: str | None
    refused: str | None
    expiries: tuple[date, ...]


def _refused(reason: str) -> EventMove:
    return EventMove(None, None, None, None, reason, ())


def event_move(
    smiles: Sequence[Smile],
    quoted_at: datetime,
    reaction: tuple[date, date] | None,
    *,
    estimated: bool,
) -> EventMove:
    """The report's implied move from the smiles' ATM vols. ``reaction`` is
    the (earliest, latest) session that may trade on it."""
    if reaction is None:
        return _refused("no earnings date")
    first, last = reaction
    today = quoted_at.astimezone(mc.ET).date()
    if last <= today:
        return _refused("the report has already traded")

    def sessions(s: Smile) -> int:
        return mc.sessions_between(today, s.expiry)

    def variance(s: Smile) -> float:
        return s.atm_vol * s.atm_vol * s.years

    ordered = sorted(smiles, key=lambda s: s.expiry)
    before = [s for s in ordered if s.expiry < first and sessions(s) >= MIN_SESSIONS]
    after = [s for s in ordered if s.expiry >= last]
    if not after:
        return _refused("no listed expiry after the report")
    e2 = after[0]
    if e2.days > MAX_EVENT_DAYS:
        return _refused(f"the first expiry after the report is {round(e2.days)} days out")

    if before:
        e1 = before[-1]
        used, method = (e1, e2), "before_and_after"
        per_session = variance(e1) / sessions(e1)
    else:
        e3 = next((s for s in after[1:] if sessions(s) - sessions(e2) >= MIN_SESSIONS), None)
        if e3 is None or e3.days > MAX_EVENT_DAYS:
            return _refused("not enough expiries around the report")
        used, method = (e2, e3), "two_after"
        per_session = (variance(e3) - variance(e2)) / (sessions(e3) - sessions(e2))

    if estimated and any(
        mc.sessions_between(min(s.expiry, first), max(s.expiry, first)) <= ESTIMATE_GUARD_SESSIONS for s in used
    ):
        return _refused("the report date is an estimate and sits next to an expiry")
    event_variance = variance(e2) - per_session * sessions(e2)
    if per_session <= 0 or event_variance <= 0:
        return _refused("the expiries leave no variance for the report")
    sigma = math.sqrt(event_variance)
    return EventMove(
        event_sigma=sigma,
        implied_move=EXPECTED_ABS * sigma,
        base_vol=math.sqrt(per_session * om.TRADING_DAYS),
        method=method,
        refused=None,
        expiries=tuple(s.expiry for s in used),
    )


def past_moves(past: Sequence[Announcement], closes: Sequence[tuple[date, float]]) -> list[PastMove]:
    """Each past report's move across its reaction, oldest first, the last
    ``PAST_LIMIT``; a report whose closes (on the exact NYSE sessions) are
    missing is skipped."""
    by_day = dict(closes)
    moves: list[PastMove] = []
    for report in past:
        day = report.when.date()
        first, last = reaction_sessions(day, report.timing)
        start = mc.previous_session(first)
        if start not in by_day or last not in by_day:
            continue
        moves.append(
            PastMove(
                announced=day,
                timing=report.timing,
                move=math.log(by_day[last] / by_day[start]),
                spans_extra_day=first != last,
            )
        )
    return moves[-PAST_LIMIT:]
