"""Schemas for the owner's routes (``/v1/owner``, ADR 0009).

Positions carry tastytrade's live figures: shown to the owner, never stored,
never put in a prompt. No account number appears anywhere: accounts are
numbered 1, 2, ... in the order tastytrade lists them.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class OwnerStatus(BaseModel):
    """What's set up for the owner. The unlock form reads it to check a key."""

    tastytrade: bool


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
    accounts: int
    groups: list[PositionGroup]
    unanalysed: list[UnanalysedPosition]
    source: Literal["tastytrade"] = "tastytrade"
    # tastytrade failed and this is the last copy read (``as_of`` says when).
    stale: bool = False
    # More accounts or positions than one read takes (owner_positions.MAX_ACCOUNTS, MAX_POSITIONS).
    truncated: bool = False
