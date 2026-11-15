"""
Where one expiry's open interest sits: totals, the largest contracts, max
pain, and gamma and delta exposure by strike with the walls and the gamma
flip. Computed from Yahoo's open interest and our own IVs (the expiry's
smile), never Yahoo's IV column.

**Gamma exposure rests on an assumption,** the common one: dealers are
long the calls and short the puts that customers hold opposite them, so
call gamma counts plus and put gamma minus. Real positioning isn't public;
the page states the assumption beside the numbers. **Delta exposure** is
the open options' own delta (calls plus, puts minus), as OptionCharts
counts it, with no assumption about who holds them.

Units are dollars per 1% move of the stock. With the forward gamma
Γ = φ(d1) / (F·σ·√T) and the forward moving with the stock:

- gamma exposure at a strike = Γ · F² · open interest (× 100 shares × 1%);
- delta exposure at a strike = Δ · F · open interest, with a put's Δ = N(d1) − 1.

The gamma flip holds each strike's IV where it is (sticky strike), moves
the stock across ±25% in 0.5% steps, and takes the sign change of net gamma
exposure nearest the spot, interpolated between steps. Max pain is the
settle, among the listed strikes, that leaves the most open contracts
worthless: the one that pays holders least.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas.options import Positioning, StrikeExposure, TopContract
from app.services import options_math as om
from app.services.options_chain import ExpiryQuotes
from app.services.options_metrics import Smile

ASSUMPTION = (
    "Gamma exposure assumes dealers are long the calls and short the puts customers hold opposite them, "
    "the common convention; actual positions aren't public. Delta exposure is the open options' own delta, "
    "calls positive and puts negative, with no assumption about who holds them."
)
TOP_CONTRACTS = 10
FLIP_RANGE = 0.25
FLIP_STEP = 0.005
_MIN_YEARS = 1 / (365 * 24)  # an hour: an expiring option still has a defined gamma


def _open_interest(chain: ExpiryQuotes) -> tuple[dict[float, int], dict[float, int]]:
    calls: dict[float, int] = {}
    puts: dict[float, int] = {}
    for quote in chain.calls:
        calls[quote.strike] = calls.get(quote.strike, 0) + quote.open_interest
    for quote in chain.puts:
        puts[quote.strike] = puts.get(quote.strike, 0) + quote.open_interest
    return calls, puts


def max_pain(chain: ExpiryQuotes) -> float | None:
    """The listed strike that, as the settle, pays option holders least.
    One pass with running sums, not every strike against every strike: at
    a settle S the calls below pay S·Σoi − Σ(K·oi), the puts above
    Σ(K·oi) − S·Σoi."""
    calls, puts = _open_interest(chain)
    if not any(calls.values()) and not any(puts.values()):
        return None
    strikes = sorted(calls.keys() | puts.keys())
    put_count = sum(puts.values())
    put_weight = sum(k * oi for k, oi in puts.items())
    call_count = call_weight = 0.0
    best: tuple[float, float] | None = None  # (payout, strike)
    for k in strikes:
        # Puts at k pay nothing at a settle of k: drop them before pricing it.
        put_count -= puts.get(k, 0)
        put_weight -= k * puts.get(k, 0)
        paid = (k * call_count - call_weight) + (put_weight - k * put_count)
        if best is None or paid < best[0]:
            best = (paid, k)
        call_count += calls.get(k, 0)
        call_weight += k * calls.get(k, 0)
    return best[1] if best else None


def _vol_at(s: Smile, strike: float) -> float:
    """The smile's IV at ``strike``: linear between its points, flat beyond."""
    xs = [k for k, _ in s.points]
    ys = [v for _, v in s.points]
    if not xs:
        return s.atm_vol
    if strike <= xs[0]:
        return ys[0]
    if strike >= xs[-1]:
        return ys[-1]
    return om.interpolate(strike, xs, ys) or s.atm_vol


def _net_gamma(forward: float, years: float, vols: dict[float, float], net_oi: dict[float, int]) -> float:
    return sum(om.gamma76(forward, k, years, vols[k]) * forward * forward * oi for k, oi in net_oi.items() if oi)


def gamma_flip(s: Smile, spot: float, vols: dict[float, float], net_oi: dict[float, int]) -> float | None:
    """The stock price nearest ``spot`` where net gamma exposure changes sign."""
    years = max(s.years, _MIN_YEARS)
    steps = round(FLIP_RANGE / FLIP_STEP)
    prices = [spot * (1 + i * FLIP_STEP) for i in range(-steps, steps + 1)]
    values = [_net_gamma(s.forward * p / spot, years, vols, net_oi) for p in prices]
    # A strict change of sign only: net gamma that is zero throughout (calls
    # and puts matched at every strike) has no flip.
    crossings = [
        p0 + (p1 - p0) * v0 / (v0 - v1)
        for p0, p1, v0, v1 in zip(prices, prices[1:], values, values[1:], strict=False)
        if v0 * v1 < 0
    ]
    return min(crossings, key=lambda p: abs(p - spot), default=None)


@dataclass(frozen=True)
class _Strike:
    strike: float
    call_gex: float
    put_gex: float
    call_dex: float
    put_dex: float

    def row(self) -> StrikeExposure:
        """The payload's row: net figures in whole dollars, one per strike shown."""
        return StrikeExposure(
            strike=self.strike,
            gex=round(self.call_gex + self.put_gex),
            dex=round(self.call_dex + self.put_dex),
        )


def headline(chain: ExpiryQuotes, s: Smile) -> tuple[float | None, float]:
    """(max pain, net gamma exposure) for the across-expiries table: no
    by-strike rows and no flip, so it stays cheap over every expiry read."""
    calls, puts = _open_interest(chain)
    years = max(s.years, _MIN_YEARS)
    net = sum(
        om.gamma76(s.forward, k, years, _vol_at(s, k)) * s.forward * s.forward * (calls.get(k, 0) - puts.get(k, 0))
        for k in calls.keys() | puts.keys()
        if calls.get(k, 0) != puts.get(k, 0)
    )
    return max_pain(chain), net


def positioning(chain: ExpiryQuotes, s: Smile, spot: float, shown: Iterable[float] | None = None) -> Positioning:
    """``shown`` limits the by-strike rows (the open interest chart's
    strikes); totals, nets, walls and the flip count every strike."""
    calls, puts = _open_interest(chain)
    strikes = sorted(k for k in calls.keys() | puts.keys() if calls.get(k, 0) or puts.get(k, 0))
    years = max(s.years, _MIN_YEARS)
    vols = {k: _vol_at(s, k) for k in strikes}
    window = set(shown) if shown is not None else None
    exposure: list[_Strike] = []
    for k in strikes:
        gamma = om.gamma76(s.forward, k, years, vols[k]) * s.forward * s.forward
        delta = om.delta76(s.forward, k, years, vols[k])
        exposure.append(_Strike(
            strike=k,
            call_gex=gamma * calls.get(k, 0),
            put_gex=-gamma * puts.get(k, 0),
            call_dex=delta * s.forward * calls.get(k, 0),
            put_dex=(delta - 1) * s.forward * puts.get(k, 0),
        ))
    shown_rows = [e.row() for e in exposure if window is None or e.strike in window]
    call_oi, put_oi = sum(calls.values()), sum(puts.values())
    contracts = [TopContract(strike=k, side="call", open_interest=oi) for k, oi in calls.items() if oi] + [
        TopContract(strike=k, side="put", open_interest=oi) for k, oi in puts.items() if oi
    ]
    contracts.sort(key=lambda c: (-c.open_interest, c.strike))
    call_gex = sum(e.call_gex for e in exposure)
    put_gex = sum(e.put_gex for e in exposure)
    call_dex = sum(e.call_dex for e in exposure)
    put_dex = sum(e.put_dex for e in exposure)
    with_calls = [e for e in exposure if e.call_gex > 0]
    with_puts = [e for e in exposure if e.put_gex < 0]
    net_oi = {k: calls.get(k, 0) - puts.get(k, 0) for k in strikes}
    return Positioning(
        call_open_interest=call_oi,
        put_open_interest=put_oi,
        put_call=put_oi / call_oi if call_oi else None,
        top=contracts[:TOP_CONTRACTS],
        max_pain=max_pain(chain),
        exposure=shown_rows,
        call_gex=call_gex,
        put_gex=put_gex,
        net_gex=call_gex + put_gex,
        call_dex=call_dex,
        put_dex=put_dex,
        net_dex=call_dex + put_dex,
        call_wall=max(with_calls, key=lambda e: e.call_gex).strike if with_calls else None,
        put_wall=min(with_puts, key=lambda e: e.put_gex).strike if with_puts else None,
        gamma_flip=gamma_flip(s, spot, vols, net_oi) if strikes and spot > 0 else None,
        assumption=ASSUMPTION,
    )
