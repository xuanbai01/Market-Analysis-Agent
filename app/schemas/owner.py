"""Schemas for the owner's routes (``/v1/owner``, ADR 0009).

Positions carry tastytrade's live figures: shown to the owner, never stored,
never put in a prompt. No account number appears anywhere: accounts are
numbered 1, 2, ... in the order tastytrade lists them.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.options import ExpiryChain


class OwnerStatus(BaseModel):
    """What's set up for the owner. The unlock form reads it to check a key."""

    tastytrade: bool
    # The trade copy's key is set (OWNER_VAULT_KEY).
    vault: bool = False


class LiveQuote(BaseModel):
    """tastytrade's quote for one symbol. Greeks are per share, as tastytrade
    gives them; ``iv`` is a fraction (0.48 = 48%)."""

    bid: float | None = None
    ask: float | None = None
    mark: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    updated_at: datetime | None = None


class PositionLeg(BaseModel):
    """One open position. ``quantity`` is signed (short is negative)."""

    account: int
    kind: Literal["call", "put", "stock"]
    symbol: str
    expiry: date | None = None
    strike: float | None = None
    quantity: float
    multiplier: int
    average_open: float | None = None
    # A contract whose deliverable isn't 100 plain shares (after a split or a
    # merger): listed, but its payoff isn't modelled.
    adjusted: bool = False
    # When an option's expiry closes, from our calendar: 4 pm New York, 1 pm
    # on NYSE's half days (market_calendar.session_close). None for stock.
    expires_at: datetime | None = None
    quote: LiveQuote | None = None


class PositionGroup(BaseModel):
    """Everything open on one underlying, across accounts."""

    underlying: str  # tastytrade's form, e.g. BRK/B
    symbol: str  # ours, for the options page, e.g. BRK-B
    quote: LiveQuote | None = None
    expiries: list[date]
    legs: list[PositionLeg]


class UnanalysedPosition(BaseModel):
    """A position the page lists but doesn't analyse (a future, crypto, or a
    row it couldn't read)."""

    account: int
    instrument_type: str
    symbol: str
    quantity: float | None = None


class OwnerPositions(BaseModel):
    as_of: datetime
    # When tastytrade's marks were made: ``as_of`` during a session, else the
    # last close (market_calendar.live_quote_time). Time to expiry runs from
    # here, so a weekend doesn't take two days off every option.
    priced_at: datetime | None = None
    # Accounts whose positions were read (legs keep their place in the list).
    accounts: int
    groups: list[PositionGroup]
    unanalysed: list[UnanalysedPosition]
    source: Literal["tastytrade"] = "tastytrade"
    # tastytrade failed and this is the last copy read (``as_of`` says when).
    stale: bool = False
    # More accounts or positions than one read takes (owner_positions.MAX_ACCOUNTS, MAX_POSITIONS).
    truncated: bool = False


class OwnerTrade(BaseModel):
    """One of the owner's transactions, from the encrypted copy. Amounts are
    signed: money in positive, money out negative; fees are their total."""

    id: int
    account: int
    executed_at: str | None = None
    date: str | None = None
    type: str | None = None
    sub_type: str | None = None
    action: str | None = None
    symbol: str | None = None
    underlying: str | None = None
    instrument_type: str | None = None
    quantity: float | None = None
    price: float | None = None
    value: float | None = None
    fees: float = 0.0
    net_value: float | None = None
    description: str | None = None
    # tastytrade's order the fill belongs to (the legs of one strategy share
    # it), and the transaction this one cancels, if it's a reversal.
    order_id: int | None = None
    reverses_id: int | None = None


class JournalLeg(BaseModel):
    """One contract a position opened: ``quantity`` signed (short negative),
    ``closed`` how much of it has been closed since."""

    symbol: str
    kind: Literal["call", "put", "stock"]
    expiry: date | None = None
    strike: float | None = None
    quantity: float
    closed: float = 0.0


class JournalPosition(BaseModel):
    """What one order opened (or one assignment delivered), and how it ended.
    Cash is signed like the trades: money in positive."""

    id: str
    account: int
    underlying: str
    structure: str
    legs: list[JournalLeg]
    opened_at: str | None = None
    closed_at: str | None = None
    # The trading days (transaction dates), shown and counted: a fill at 8 pm
    # New York is the next day in UTC.
    opened_on: date | None = None
    closed_on: date | None = None
    days_held: int | None = None
    status: Literal["open", "closed", "partly_closed"]
    ended_by: Literal["closed", "expired", "assigned", "exercised", "mixed"] | None = None
    # Stock delivered by an assignment or exercise, and the option's position.
    origin: Literal["assignment", "exercise"] | None = None
    origin_position: str | None = None
    open_cash: float | None = None
    close_cash: float | None = None
    fees: float = 0.0
    # On the closed part, fees in; None while nothing is closed, or when it
    # can't be told (after a split, or a fill without its net value).
    realized: float | None = None
    rolled_from: str | None = None
    rolled_to: str | None = None
    note: str | None = None
    transactions: list[int] = Field(default_factory=list)


class MonthTotal(BaseModel):
    month: str  # YYYY-MM, of the close
    realized: float


class UnderlyingTotal(BaseModel):
    underlying: str
    realized: float


class UnmatchedRow(BaseModel):
    id: int
    date: str | None = None
    symbol: str | None = None
    reason: str


class JournalTotals(BaseModel):
    realized: float = 0.0
    # Closed positions with a computed P&L, and those without one (after a
    # split, say): counted apart, not as closed at 0.
    closed: int = 0
    profitable: int = 0
    # Positions closed in part, whose closed parts ``realized`` includes.
    partly: int = 0
    unpriced: int = 0
    average_days: float | None = None
    # The fees inside ``realized``: the closed parts' own, not an open
    # position's entry fees.
    fees: float = 0.0


class TradeJournal(BaseModel):
    positions: list[JournalPosition] = Field(default_factory=list)
    months: list[MonthTotal] = Field(default_factory=list)
    underlyings: list[UnderlyingTotal] = Field(default_factory=list)
    totals: JournalTotals = Field(default_factory=JournalTotals)
    unmatched: list[UnmatchedRow] = Field(default_factory=list)


class OwnerTrades(BaseModel):
    trades: list[OwnerTrade]
    # False when this visit couldn't reach tastytrade: the copy as it stood.
    synced: bool
    reason: str | None = None
    # The trades read as positions (``trade_journal``): computed on each
    # visit, never stored.
    journal: TradeJournal = Field(default_factory=TradeJournal)


class LiveChain(BaseModel):
    """One expiry's chain at tastytrade's live quotes (owner_live_chain): the
    same shape as the delayed chain, our own IVs from their mids. Shown to the
    owner only; never stored."""

    symbol: str
    expiry: date
    spot: float
    # The time the IVs are figured from (the last close outside a session).
    quoted_at: datetime
    # The newest of tastytrade's quote times.
    updated_at: datetime | None = None
    chain: ExpiryChain
    source: Literal["tastytrade"] = "tastytrade"

