"""
The cited read of an options report (ADR 0008, PR5).

An AI-written headline and a few points on what one stock's option
prices say, written from the report's claims and nothing else: code
computes every figure and the direction of every comparison (ADR 0007),
the model only writes. Each point cites the claims it quotes, and any
point quoting a number none of its cited claims shows is dropped here,
in code, before anyone sees it, so every number on the card has its
chip; a headline with a number no claim shows spoils the read.

Reads are cached per symbol and quote time, so one set of quotes is read
once: overnight and at weekends one read stands until the next session,
and in a session a new one is written only when the report itself is
rebuilt (every 15 minutes, on a visit).
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.options import OptionsRead, OptionsReadDraft, OptionsReport
from app.schemas.research import ClaimRef, ThesisPoint
from app.services import llm, options_report, research_thesis
from app.services import market_calendar as mc
from app.services.claim_display import format_claim_line

logger = logging.getLogger(__name__)

READ_SECTION = "Options"
MAX_POINTS = 5
CACHE_SIZE = 30

READ_SYSTEM_PROMPT = """\
You are an options analyst explaining what one stock's option prices say. \
The user gives computed facts about the stock's options; each line starts \
with an id in brackets ("[O3]"). Write:

- ``headline``: one sentence, the main thing the prices say: how much \
movement options price against what the stock has shown, the shape of the \
term structure, the next report's priced move against past reports, or \
where IV30 sits in its stored history.
- ``points``: 3 to 5 points, each one or two sentences and at most 40 \
words, each with a ``title`` of 2 to 6 plain words and no numbers. Cover \
implied against realized volatility, the term structure, the skew and open \
interest, and, when the facts give them, the earnings move and the IV \
history. Each point lists in ``claim_ids`` the id of every fact it quotes, \
exactly as written in the brackets.

Rules (non-negotiable):
1. Every number in your text must be a value shown in the fact lines, in \
the display units shown, written in digits exactly as shown. Never compute \
a number yourself, never round, approximate or spell one out. Write dates \
as they appear (2026-11-17).
2. A comparison's direction is in its fact's words ("above", "slopes \
down", "more puts open than calls"): use those words and drop the sign.
3. These are risk-neutral prices: say what options price ("options price \
a 7.12% move"), never what the stock will do. No forecasts.
4. No advice: never suggest buying, selling or any trade or strategy, and \
never call options cheap, expensive, rich or a bargain.
5. No outside facts: no news, products, events or reasons why. Whatever \
you know about this company from elsewhere stays out.
6. Plain prose, no markdown.
7. Set two figures side by side only when a fact states that comparison \
(its words say above, below or level with). The expected move to an \
expiry is one standard deviation over all its days, not an earnings move: \
never compare it with past reports' moves.
"""


class NothingToRead(Exception):
    """The symbol lists no options, or none could be priced."""


class ReadUnavailable(Exception):
    """The model wrote nothing usable this time; not cached, so the next
    visit tries again."""


_cache: OrderedDict[tuple[str, datetime], OptionsRead] = OrderedDict()
_locks: dict[tuple[str, datetime], asyncio.Lock] = {}
# Visits holding or waiting for each lock: it goes when the last one does,
# so a new visit never makes a second lock while others still wait.
_waiting: dict[tuple[str, datetime], int] = {}


def clear_cache() -> None:
    _cache.clear()
    _locks.clear()
    _waiting.clear()


def _remember(key: tuple[str, datetime], read: OptionsRead) -> None:
    _cache[key] = read
    _cache.move_to_end(key)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


def has_read(symbol: str) -> bool:
    """Whether a read of the cached report is cached too: such a request
    costs no model call."""
    report = options_report.fresh_report(symbol)
    return report is not None and (symbol, report.quoted_at) in _cache


def _quote_line(report: OptionsReport) -> str:
    when = report.quoted_at.astimezone(mc.ET)
    if report.at_close:
        return f"Quotes: the close of {when.date().isoformat()}"
    return f"Quotes: {when:%Y-%m-%d %H:%M} ET, about 15 minutes delayed"


def prompt(report: OptionsReport) -> str:
    """The symbol (validated by the route), the quote time and the facts:
    nothing a caller typed beyond the ticker."""
    lines = [f"Symbol: {report.symbol}", _quote_line(report), ""]
    lines += [format_claim_line(c, claim_id=f"O{i + 1}") for i, c in enumerate(report.claims)]
    return "\n".join(lines)


def _backed(points: list[ThesisPoint], report: OptionsReport) -> list[ThesisPoint]:
    """The points whose every figure is one of the claims they cite, so each
    number on the card has its chip; a label any claim names ("IV30", "the
    last 8 reports") is fine."""
    kept = []
    for point in points:
        cited = [report.claims[ref.index] for ref in point.claim_refs]
        stray = research_thesis.unbacked_numbers(point.text, cited, labels=report.claims)
        if stray:
            logger.warning("options read for %s: dropped a point quoting %s, which no fact it cites shows", report.symbol, stray)
            continue
        kept.append(point)
    return kept


async def write_read(report: OptionsReport, now: datetime) -> OptionsRead | None:
    """The read of ``report``; None when the model fails or writes nothing
    that survives the checks."""
    if report.status != "ok" or not report.claims:
        return None
    ids = {f"O{i + 1}": ClaimRef(section=READ_SECTION, index=i) for i in range(len(report.claims))}
    try:
        draft: Any = await llm.synth_call(prompt=prompt(report), schema=OptionsReadDraft, system=READ_SYSTEM_PROMPT)
    except Exception:
        logger.exception("options read for %s failed", report.symbol)
        return None
    if not isinstance(draft, OptionsReadDraft) or not draft.headline.strip():
        logger.warning("options read for %s: the model returned no headline", report.symbol)
        return None
    headline = draft.headline.strip()
    if stray := research_thesis.unbacked_numbers(headline, report.claims):
        logger.warning("options read for %s: the headline quotes %s, which no fact shows", report.symbol, stray)
        return None
    points = research_thesis.resolve_points(
        draft.points, ids, MAX_POINTS, {READ_SECTION: report.claims}, max_refs=None
    )
    points = _backed(points, report)
    if not points:
        logger.warning("options read for %s: none of %d drafted points survived", report.symbol, len(draft.points))
        return None
    return OptionsRead(
        symbol=report.symbol,
        quoted_at=report.quoted_at,
        at_close=report.at_close,
        headline=headline,
        points=points,
        claims=report.claims,
        generated_at=now,
    )


async def get_read(session: AsyncSession, symbol: str, *, now: datetime | None = None) -> OptionsRead:
    """The read of the symbol's current report: cached, else written (one
    model call per set of quotes, however many visits ask at once)."""
    report = await options_report.get_report(session, symbol, now=now)
    # No database connection held through the model call (CLAUDE.md): the
    # report recorded the view and committed, but a failed history read can
    # leave a transaction open. Closing releases it; the session reopens if
    # used again.
    await session.close()
    if report.status != "ok":
        raise NothingToRead(symbol)
    key = (symbol, report.quoted_at)
    if key in _cache:
        return _cache[key]
    lock = _locks.setdefault(key, asyncio.Lock())
    _waiting[key] = _waiting.get(key, 0) + 1
    try:
        async with lock:
            if key in _cache:
                return _cache[key]
            read = await write_read(report, now or datetime.now(UTC))
            if read is None:
                raise ReadUnavailable(symbol)
            _remember(key, read)
            return read
    finally:
        _waiting[key] -= 1
        if _waiting[key] == 0:
            del _waiting[key]
            _locks.pop(key, None)
