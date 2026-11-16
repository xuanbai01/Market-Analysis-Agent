"""The owner's trades read as a journal (tastytrade PR D, ADR 0009).

From the transactions in the encrypted copy (``owner_trades``) to positions:
every lot one order opened, matched first in, first out against the fills
that closed it, per account and contract. Each position is named from its
legs (``trade_structures``), says how it ended (closed, expired, assigned,
exercised), and carries its realized P&L, fees in.

Pure: computed on each visit, never stored, never in a prompt; facts about
past trades, nothing about what to do next. What it can't read is listed as
unmatched with the reason, never guessed:
- a close with nothing open to match: history before the copy starts, or a
  transfer in;
- a fill with neither buy nor sell (a split, a symbol change): not modelled,
  and that contract's later P&L isn't computed;
- an option whose symbol isn't an OCC one.

An assignment or exercise closes the option at no cash (its premium stays
with it, "assigned") and delivers stock as a position of its own, opened at
the strike. A reversal and the fill it cancels both leave the matching.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from app.schemas.owner import (
    JournalLeg,
    JournalPosition,
    JournalTotals,
    MonthTotal,
    OwnerTrade,
    TradeJournal,
    UnderlyingTotal,
    UnmatchedRow,
)
from app.services.owner_positions import parse_occ
from app.services.owner_trades import chronological
from app.services.trade_structures import structure

ENDINGS = {
    "Expiration": "expired",
    "Assignment": "assigned",
    "Cash Settled Assignment": "assigned",
    "Exercise": "exercised",
    "Cash Settled Exercise": "exercised",
}
DELIVERIES = {"assigned": "assignment", "exercised": "exercise"}
EPS = 1e-9
CENTS = 2

Key = tuple[int, str]  # account, contract symbol


@dataclass
class _Lot:
    position: str
    sign: int  # +1 long, -1 short
    remaining: float
    unit_cash: float | None  # signed cash per unit at the open
    unit_fees: float


@dataclass
class _Position:
    id: str
    account: int
    underlying: str
    opened_at: datetime
    legs: dict[str, JournalLeg] = field(default_factory=dict)
    open_cash: float | None = 0.0
    close_cash: float | None = 0.0
    fees: float = 0.0
    realized: float = 0.0
    unknown: bool = False  # some closed part's P&L can't be told
    # Each closed part's (month, P&L, fees in it): summed into the totals
    # only when the whole position's P&L can be told, so the totals hold
    # just what the positions show.
    parts: list[tuple[str, float, float]] = field(default_factory=list)
    endings: set[str] = field(default_factory=set)
    closed_at: datetime | None = None
    origin: str | None = None
    delivered_by: tuple[str, str, str] | None = None  # date, underlying, ending
    note: str | None = None
    transactions: list[int] = field(default_factory=list)


def _add(total: float | None, part: float | None) -> float | None:
    return None if total is None or part is None else total + part


def _contract(trade: OwnerTrade) -> tuple[str, date | None, float | None] | None:
    """(kind, expiry, strike); stock for a symbol that isn't an option, None
    for an option whose symbol doesn't read."""
    try:
        occ = parse_occ(trade.symbol or "")
    except ValueError:
        is_option = "option" in (trade.instrument_type or "").lower()
        return None if is_option else ("stock", None, None)
    return occ.kind, occ.expiry, occ.strike


class _Journal:
    def __init__(self) -> None:
        self.positions: dict[str, _Position] = {}
        self.lots: dict[Key, list[_Lot]] = defaultdict(list)
        self.flagged: dict[Key, str] = {}  # contract -> the action not modelled
        self.closed_by_order: dict[int, list[str]] = defaultdict(list)
        # Options closed by an assignment or exercise: (date, underlying, ending, position).
        self.delivered: list[tuple[str, str, str, str]] = []
        self.unmatched: list[UnmatchedRow] = []

    def _unmatched(self, trade: OwnerTrade, reason: str) -> None:
        self.unmatched.append(UnmatchedRow(id=trade.id, date=trade.date, symbol=trade.symbol, reason=reason))

    def add(self, trade: OwnerTrade) -> None:
        if not trade.symbol or trade.quantity is None or trade.quantity <= 0:
            return  # a money movement: no position to match
        action = (trade.action or "").lower()
        direction = 1 if "buy" in action else -1 if "sell" in action else 0
        key = (trade.account, trade.symbol)
        if direction == 0 and (trade.sub_type or "") in ENDINGS and self.lots[key]:
            # An expiry, assignment or exercise sent without a buy or sell
            # only removes what's open.
            direction = -self.lots[key][0].sign
            action = "to close"
        if direction == 0:
            what = trade.sub_type or trade.type or "an action with no buy or sell"
            self._unmatched(trade, f"not modelled: {what}")
            self.flagged[key] = what
            return
        contract = _contract(trade)
        if contract is None:
            self._unmatched(trade, "not a contract symbol tastytrade's format reads")
            return
        quantity = trade.quantity
        unit_cash = None if trade.net_value is None else trade.net_value / quantity
        unit_fees = trade.fees / quantity
        remaining = quantity
        if "to open" not in action:
            remaining = self._close(trade, key, direction, remaining, unit_cash, unit_fees, contract[0])
            if remaining > EPS and "to close" in action:
                reason = "nothing open to close: it may come from before the copy starts"
                if remaining < quantity - EPS:  # part of it closed what was open
                    reason = f"{remaining:g} of {quantity:g} had {reason}"
                self._unmatched(trade, reason)
                return
        if remaining > EPS:
            self._open(trade, key, direction, remaining, unit_cash, unit_fees, contract)

    def _close(
        self, trade: OwnerTrade, key: Key, direction: int, remaining: float,
        unit_cash: float | None, unit_fees: float, kind: str,
    ) -> float:
        lots = self.lots[key]
        ending = ENDINGS.get(trade.sub_type or "", "closed")
        when = chronological(trade)[0]
        while remaining > EPS:
            # The oldest lot this fill closes, wherever it's queued.
            index = next((i for i, lot in enumerate(lots) if lot.sign == -direction), None)
            if index is None:
                break
            lot = lots[index]
            size = min(remaining, lot.remaining)
            position = self.positions[lot.position]
            part = None if lot.unit_cash is None or unit_cash is None else (lot.unit_cash + unit_cash) * size
            if key in self.flagged:
                part = None
                position.note = f"After a {self.flagged[key].lower()}, the P&L isn't computed."
            elif (trade.sub_type or "").startswith("Cash Settled") and not trade.net_value:
                # The settlement wasn't on this fill: booked apart, so not guessed.
                part = None
                position.note = "Cash-settled, with the settlement booked apart from the fill: the P&L isn't computed."
            if part is None:
                position.unknown = True
            else:
                position.realized += part
                position.parts.append((when.strftime("%Y-%m"), part, (lot.unit_fees + unit_fees) * size))
            position.close_cash = _add(position.close_cash, None if unit_cash is None else unit_cash * size)
            position.fees += unit_fees * size
            position.legs[key[1]].closed += size
            position.endings.add(ending)
            position.closed_at = when
            if trade.id not in position.transactions:
                position.transactions.append(trade.id)
            if trade.order_id is not None and position.id not in self.closed_by_order[trade.order_id]:
                self.closed_by_order[trade.order_id].append(position.id)
            if ending in DELIVERIES and kind != "stock":
                self.delivered.append((trade.date or "", position.underlying, ending, position.id))
            lot.remaining -= size
            remaining -= size
            if lot.remaining <= EPS:
                lots.pop(index)
        return remaining

    def _open(
        self, trade: OwnerTrade, key: Key, direction: int, size: float, unit_cash: float | None,
        unit_fees: float, contract: tuple[str, date | None, float | None],
    ) -> None:
        kind, expiry, strike = contract
        ending = ENDINGS.get(trade.sub_type or "")
        if trade.order_id is not None:
            pid = f"order-{trade.order_id}"
        else:  # delivered by an assignment or exercise, or another fill without an order
            pid = f"{(trade.sub_type or trade.type or 'fill').lower().replace(' ', '-')}-{trade.date}-{trade.underlying}"
        position = self.positions.get(pid)
        if position is None:
            position = _Position(
                id=pid, account=trade.account, underlying=trade.underlying or trade.symbol or "?",
                opened_at=chronological(trade)[0],
            )
            self.positions[pid] = position
        if kind == "stock" and ending in DELIVERIES:
            position.origin = DELIVERIES[ending]
            position.delivered_by = (trade.date or "", position.underlying, ending)
        self.lots[key].append(_Lot(pid, direction, size, unit_cash, unit_fees))
        leg = position.legs.setdefault(key[1], JournalLeg(symbol=key[1], kind=kind, expiry=expiry, strike=strike, quantity=0.0))  # type: ignore[arg-type]
        leg.quantity += direction * size
        position.open_cash = _add(position.open_cash, None if unit_cash is None else unit_cash * size)
        position.fees += unit_fees * size
        if trade.id not in position.transactions:
            position.transactions.append(trade.id)

    def _rolls(self) -> dict[str, tuple[str | None, str | None]]:
        """An order that closed one position and opened another on the same
        underlying rolled it: position id -> (rolled from, rolled to)."""
        links: dict[str, tuple[str | None, str | None]] = {}
        for order, closed in self.closed_by_order.items():
            opened = self.positions.get(f"order-{order}")
            if opened is None:
                continue
            rolled = [pid for pid in closed if pid != opened.id and self.positions[pid].underlying == opened.underlying]
            if rolled:  # every position the order closed rolls into the one it opened
                links[opened.id] = (rolled[0], links.get(opened.id, (None, None))[1])
                for pid in rolled:
                    links[pid] = (links.get(pid, (None, None))[0], opened.id)
        return links

    def _delivered_from(self, delivered_by: tuple[str, str, str] | None) -> str | None:
        """The option whose assignment or exercise delivered this stock: the
        latest on the same underlying on or before its date (delivery can
        settle a session later)."""
        if delivered_by is None:
            return None
        day, underlying, ending = delivered_by
        found = [d for d in self.delivered if d[1] == underlying and d[2] == ending and d[0] <= day]
        return max(found)[3] if found else None

    def _out(self, position: _Position, links: dict[str, tuple[str | None, str | None]]) -> JournalPosition:
        legs = list(position.legs.values())
        opened = sum(abs(leg.quantity) for leg in legs)
        closed = sum(leg.closed for leg in legs)
        status = "open" if closed <= EPS else "closed" if closed >= opened - EPS else "partly_closed"
        ended_by = None
        if status != "open":
            ended_by = next(iter(position.endings)) if len(position.endings) == 1 else "mixed"
        realized = None if status == "open" or position.unknown else round(position.realized, CENTS)
        days = (position.closed_at.date() - position.opened_at.date()).days if status == "closed" and position.closed_at else None
        rolled_from, rolled_to = links.get(position.id, (None, None))
        return JournalPosition(
            id=position.id, account=position.account, underlying=position.underlying,
            structure=structure(legs, position.open_cash), legs=legs,
            opened_at=position.opened_at.isoformat(),
            closed_at=position.closed_at.isoformat() if position.closed_at and status == "closed" else None,
            days_held=days, status=status, ended_by=ended_by,  # type: ignore[arg-type]
            origin=position.origin,  # type: ignore[arg-type]
            origin_position=self._delivered_from(position.delivered_by),
            open_cash=None if position.open_cash is None else round(position.open_cash, CENTS),
            close_cash=None if position.close_cash is None or status == "open" else round(position.close_cash, CENTS),
            fees=round(position.fees, CENTS), realized=realized,
            rolled_from=rolled_from, rolled_to=rolled_to, note=position.note,
            transactions=position.transactions,
        )

    def journal(self) -> TradeJournal:
        links = self._rolls()
        positions = [self._out(position, links) for position in self.positions.values()]
        months: dict[str, float] = defaultdict(float)
        underlyings: dict[str, float] = defaultdict(float)
        fees = 0.0
        for position in self.positions.values():
            if position.unknown:
                continue  # shown as no P&L: none of it in the totals
            for month, part, part_fees in position.parts:
                months[month] += part
                underlyings[position.underlying] += part
                fees += part_fees
        done = [p for p in positions if p.status == "closed"]
        closed = [p for p in done if p.realized is not None]
        days = [p.days_held for p in closed if p.days_held is not None]
        return TradeJournal(
            positions=positions,
            months=[MonthTotal(month=m, realized=round(v, CENTS)) for m, v in sorted(months.items())],
            underlyings=[UnderlyingTotal(underlying=u, realized=round(v, CENTS)) for u, v in sorted(underlyings.items())],
            totals=JournalTotals(
                realized=round(sum(months.values()), CENTS),
                closed=len(closed),
                profitable=sum(1 for p in closed if p.realized is not None and p.realized > 0),
                partly=sum(1 for p in positions if p.status == "partly_closed" and p.realized is not None),
                unpriced=len(done) - len(closed),
                average_days=round(sum(days) / len(days), 1) if days else None,
                fees=round(fees, CENTS),
            ),
            unmatched=self.unmatched,
        )


def build_journal(trades: list[OwnerTrade]) -> TradeJournal:
    """The trades, oldest first, read as positions. CPU: callers run it off
    the event loop."""
    reversed_ids = {t.reverses_id for t in trades if t.reverses_id is not None}
    journal = _Journal()
    for trade in sorted(trades, key=chronological):
        if trade.reverses_id is None and trade.id not in reversed_ids:
            journal.add(trade)
    return journal.journal()


async def journal_of(trades: list[OwnerTrade]) -> TradeJournal:
    """``build_journal`` off the event loop: a long history is CPU."""
    return await asyncio.to_thread(build_journal, trades)

