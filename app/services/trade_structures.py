"""The name of what one order opened (tastytrade PR D): "call vertical,
credit", "iron condor, credit", "covered call". Read from the legs alone:
their kinds, expiries, strikes and signed sizes, and whether the order took
money in. Anything it can't name is "custom, N legs", never a guess."""
from __future__ import annotations

from app.schemas.owner import JournalLeg


def _flow(open_cash: float | None) -> str:
    if open_cash is None or open_cash == 0:
        return ""
    return ", credit" if open_cash > 0 else ", debit"


def _side(quantity: float) -> str:
    return "long" if quantity > 0 else "short"


def _two(a: JournalLeg, b: JournalLeg, flow: str) -> str | None:
    same_size = abs(a.quantity) == abs(b.quantity)
    opposite = (a.quantity > 0) != (b.quantity > 0)
    if a.kind == b.kind and same_size and opposite:
        if a.expiry == b.expiry:
            return f"{a.kind} vertical{flow}"
        return f"{a.kind} {'calendar' if a.strike == b.strike else 'diagonal'}"
    if a.kind != b.kind and a.expiry == b.expiry and same_size and not opposite:
        return f"{_side(a.quantity)} {'straddle' if a.strike == b.strike else 'strangle'}"
    return None


def _butterfly(legs: list[JournalLeg]) -> str | None:
    low, mid, high = sorted(legs, key=lambda leg: leg.strike or 0.0)
    if len({leg.kind for leg in legs}) == 1 and low.quantity == high.quantity and mid.quantity == -2 * low.quantity:
        return f"{low.kind} butterfly"
    return None


def _iron(legs: list[JournalLeg], flow: str) -> str | None:
    puts = sorted((leg for leg in legs if leg.kind == "put"), key=lambda leg: leg.strike or 0.0)
    calls = sorted((leg for leg in legs if leg.kind == "call"), key=lambda leg: leg.strike or 0.0)
    if len(puts) != 2 or len(calls) != 2 or len({abs(leg.quantity) for leg in legs}) != 1:
        return None
    long_put, short_put = puts
    short_call, long_call = calls
    shape = long_put.quantity > 0 > short_put.quantity and long_call.quantity > 0 > short_call.quantity
    if not shape or (short_put.strike or 0.0) > (short_call.strike or 0.0):
        return None
    return f"iron {'butterfly' if short_put.strike == short_call.strike else 'condor'}{flow}"


def structure(legs: list[JournalLeg], open_cash: float | None) -> str:
    """The name of a position from the legs one order opened."""
    stock = [leg for leg in legs if leg.kind == "stock"]
    options = [leg for leg in legs if leg.kind != "stock"]
    custom = f"custom, {len(legs)} legs"
    if not options:
        return "stock" if all(leg.quantity > 0 for leg in stock) else "short stock"
    if stock:
        if len(stock) == 1 and len(options) == 1 and stock[0].quantity > 0:
            option = options[0]
            if option.kind == "call" and option.quantity < 0:
                return "covered call"
            if option.kind == "put" and option.quantity > 0:
                return "protective put"
        return custom
    flow = _flow(open_cash)
    one_expiry = len({leg.expiry for leg in options}) == 1
    named: str | None = None
    if len(options) == 1:
        named = f"{_side(options[0].quantity)} {options[0].kind}"
    elif len(options) == 2:
        a, b = sorted(options, key=lambda leg: (leg.expiry, leg.strike or 0.0))
        named = _two(a, b, flow)
    elif len(options) == 3 and one_expiry:
        named = _butterfly(options)
    elif len(options) == 4 and one_expiry:
        named = _iron(options, flow)
    return named or custom
