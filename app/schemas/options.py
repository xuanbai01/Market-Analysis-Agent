"""Response schemas for the options routes (ADR 0008)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.research import Claim


class FailedTicker(BaseModel):
    symbol: str
    reason: str = Field(description="the exception's class name; details are in the server log")


class SnapshotRun(BaseModel):
    """What one daily IV snapshot run did. The cron fails the job on
    ``market_open``, on no targets, and on any ``missing`` ticker."""

    status: Literal["ok", "no_new_session", "market_open"]
    session_date: date | None = Field(description="the trading day the run snapshots; None while the market is open")
    targets: list[str]
    written: list[str]
    skipped: list[str] = Field(description="already stored for this trading day")
    no_options: list[str]
    no_usable_quotes: list[str]
    failed: list[FailedTicker]
    deferred: list[str] = Field(description="not reached: Yahoo throttled the run, or it ran out of time")
    missing: list[str] = Field(
        default_factory=list,
        description=(
            "configured tickers (OPTIONS_SNAPSHOT_SYMBOLS) with no row for the session after this run: "
            "a day lost, or a ticker that shouldn't be configured; tracked ones are best-effort"
        ),
    )
    duration_ms: float


# ── The options page (GET /v1/options/{symbol}) ───────────────────────

Timing = Literal["before_open", "during", "after_close", "unknown"]


class ExpirySummary(BaseModel):
    """One expiry on the term structure and the expected-move cone."""

    expiry: date
    days: float = Field(description="calendar days from the quote time to 16:00 ET on the expiry")
    sessions: int = Field(description="NYSE sessions after the quote's day, up to and including the expiry")
    forward: float
    forward_from_parity: bool
    atm_iv: float = Field(description="at-the-money implied volatility, a fraction")
    expected_move: float = Field(description="one standard deviation of the log price to expiry (IV·√T), a fraction")
    low: float = Field(description="forward · e^(−IV·√T)")
    high: float = Field(description="forward · e^(+IV·√T)")
    straddle: float | None = Field(default=None, description="ATM straddle mid at the strike nearest the forward, per share")
    straddle_strike: float | None = None
    call_open_interest: int
    put_open_interest: int
    call_volume: int
    put_volume: int
    includes_earnings: bool = False


class SmilePoint(BaseModel):
    strike: float
    log_moneyness: float = Field(description="ln(strike / forward)")
    iv: float
    side: Literal["put", "call"] = Field(description="the out-of-the-money side the IV comes from")


class ChainRow(BaseModel):
    strike: float
    call_bid: float
    call_ask: float
    call_iv: float | None
    call_delta: float | None = Field(description="forward delta, N(d1)")
    call_open_interest: int
    call_volume: int
    call_usable: bool
    put_bid: float
    put_ask: float
    put_iv: float | None
    put_delta: float | None = Field(description="forward delta, N(d1) − 1")
    put_open_interest: int
    put_volume: int
    put_usable: bool


class OpenInterestPoint(BaseModel):
    strike: float
    call: int
    put: int


class ExpiryChain(BaseModel):
    """One expiry's smile, near-the-money chain and open interest by strike."""

    expiry: date
    days: float
    forward: float
    atm_iv: float | None
    smile: list[SmilePoint]
    rows: list[ChainRow]
    open_interest: list[OpenInterestPoint]


class PastMove(BaseModel):
    announced: date
    timing: Timing
    move: float = Field(description="log return across the reaction, signed")
    spans_extra_day: bool = Field(
        default=False, description="timing unknown: measured from the session before to the session after"
    )


class EarningsBlock(BaseModel):
    next_date: date | None
    next_timing: Timing | None
    estimated: bool = Field(description="Yahoo marks the date as an estimate")
    reaction_date: date | None = Field(description="the first session that trades on the report")
    implied_move: float | None = Field(
        description="the expected absolute move the options price for the report, √(2/π)·σ, a fraction"
    )
    implied_move_usd: float | None
    event_sigma: float | None = Field(description="one standard deviation of the report's log move")
    base_vol: float | None = Field(description="annualized volatility on the other sessions, with the report taken out")
    method: Literal["before_and_after", "two_after"] | None
    refused: str | None = Field(description="why there's no implied move, when there isn't")
    expiries: list[date] = Field(description="the expiries the implied move comes from")
    past: list[PastMove]
    past_mean_abs: float | None


class IvHistoryPoint(BaseModel):
    date: date
    iv30: float


class IvHistory(BaseModel):
    """The daily snapshots (ADR 0008). Percentile from 63 sessions, rank
    from 126; both rank today's live IV30 against the stored ones."""

    points: list[IvHistoryPoint]
    sessions: int
    since: date | None
    percentile: float | None = Field(description="share of stored IV30s at or below today's, 0–100")
    rank: float | None = Field(description="(today − low) / (high − low) over the stored IV30s, 0–100")


class OptionsReport(BaseModel):
    symbol: str
    name: str | None = None
    status: Literal["ok", "no_options", "no_usable_quotes"]
    spot: float | None
    quoted_at: datetime = Field(description="when the quotes were made: 15 minutes ago in a session, else the last close")
    # No default: the report is built fresh (never read back from storage),
    # so a build path that forgot it should fail, not say "delayed".
    at_close: bool = Field(description="the quotes are the last close's, not a delayed print from a session")
    rate: float
    rate_assumed: bool
    iv30: float | None
    iv30_extrapolated: bool
    iv90: float | None
    skew25: float | None
    rv20: float | None
    rv60: float | None
    put_call_open_interest: float | None = Field(description="put ÷ call open interest over the expiries read")
    put_call_volume: float | None
    expiries: list[ExpirySummary]
    listed_expiries: list[date]
    chain: ExpiryChain | None = Field(description="the expiry nearest 30 days; others at /chain/{expiry}")
    earnings: EarningsBlock | None
    history: IvHistory
    claims: list[Claim]
    generated_at: datetime
