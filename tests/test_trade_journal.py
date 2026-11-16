"""The trade journal (tastytrade PR D, ADR 0009): the owner's transactions
read as positions. FIFO per account and contract, the structure each order
opened, how it ended, and the realized P&L, fees in. Pure: built here from
constructed sequences."""
from __future__ import annotations

from datetime import date

import pytest

from app.schemas.owner import OwnerTrade
from app.services import trade_journal as tj


def occ(expiry: str, kind: str, strike: float, root: str = "NVDA") -> str:
    d = date.fromisoformat(expiry)
    return f"{root:<6}{d:%y%m%d}{kind}{round(strike * 1000):08d}"


def t(
    tid: int, day: str, action: str | None, symbol: str | None, qty: float | None, net: float | None, *,
    order: int | None = None, sub: str | None = None, kind: str = "Trade", underlying: str = "NVDA",
    fees: float = 0.0, reverses: int | None = None, account: int = 1, instrument: str | None = None,
) -> OwnerTrade:
    if instrument is None:
        instrument = "Equity" if symbol == underlying else "Equity Option"
    return OwnerTrade(
        id=tid, account=account, executed_at=f"{day}T15:00:00+00:00", date=day, type=kind, sub_type=sub or action,
        action=action, symbol=symbol, underlying=underlying, instrument_type=instrument, quantity=qty,
        net_value=net, fees=fees, order_id=order, reverses_id=reverses,
    )


C175, C180 = occ("2026-12-18", "C", 175), occ("2026-12-18", "C", 180)


def by_id(journal: tj.TradeJournal) -> dict[str, tj.JournalPosition]:
    return {p.id: p for p in journal.positions}


def test_a_vertical_opened_and_closed() -> None:
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 1, 480.0, order=10),
        t(2, "2026-10-01", "Buy to Open", C180, 1, -300.0, order=10),
        t(3, "2026-10-21", "Buy to Close", C175, 1, -200.0, order=11),
        t(4, "2026-10-21", "Sell to Close", C180, 1, 100.0, order=11),
    ])
    (p,) = j.positions
    assert p.structure == "call vertical, credit"
    assert (p.status, p.ended_by) == ("closed", "closed")
    assert p.realized == pytest.approx(80.0)
    assert p.days_held == 20
    assert p.transactions == [1, 2, 3, 4]
    assert j.totals.realized == pytest.approx(80.0) and j.totals.closed == 1 and j.totals.profitable == 1


def test_an_iron_condor_that_expires_keeps_its_credit() -> None:
    legs = [("P", 150, "Buy to Open", -50.0), ("P", 160, "Sell to Open", 150.0), ("C", 190, "Sell to Open", 140.0), ("C", 200, "Buy to Open", -40.0)]
    rows = [t(i, "2026-11-01", action, occ("2026-11-20", k, s), 1, cash, order=20) for i, (k, s, action, cash) in enumerate(legs, start=1)]
    rows += [
        t(10 + i, "2026-11-20", "Sell to Close" if action.startswith("Buy") else "Buy to Close", occ("2026-11-20", k, s), 1, 0.0,
          sub="Expiration", kind="Receive Deliver")
        for i, (k, s, action, _cash) in enumerate(legs, start=1)
    ]
    (p,) = tj.build_journal(rows).positions
    assert p.structure == "iron condor, credit"
    assert (p.status, p.ended_by) == ("closed", "expired")
    assert p.realized == pytest.approx(200.0)


def test_a_put_assigned_its_stock_and_a_call_on_it() -> None:
    p150, c160 = occ("2026-11-20", "P", 150), occ("2026-12-18", "C", 160)
    j = tj.build_journal([
        t(1, "2026-11-01", "Sell to Open", p150, 1, 300.0, order=30),
        t(2, "2026-11-20", "Buy to Close", p150, 1, 0.0, sub="Assignment", kind="Receive Deliver"),
        t(3, "2026-11-20", "Buy to Open", "NVDA", 100, -15000.0, sub="Assignment", kind="Receive Deliver"),
        t(4, "2026-11-23", "Sell to Open", c160, 1, 200.0, order=31),
        t(5, "2026-12-18", "Buy to Close", c160, 1, 0.0, sub="Assignment", kind="Receive Deliver"),
        t(6, "2026-12-18", "Sell to Close", "NVDA", 100, 16000.0, sub="Assignment", kind="Receive Deliver"),
    ])
    put, call = by_id(j)["order-30"], by_id(j)["order-31"]
    (stock,) = (p for p in j.positions if p.structure == "stock")
    assert (put.ended_by, put.realized) == ("assigned", pytest.approx(300.0))
    assert (call.structure, call.ended_by, call.realized) == ("short call", "assigned", pytest.approx(200.0))
    assert stock.origin == "assignment" and stock.origin_position == "order-30"
    assert (stock.ended_by, stock.realized) == ("assigned", pytest.approx(1000.0))
    assert j.totals.realized == pytest.approx(1500.0)


def test_closes_take_the_oldest_lots_first() -> None:
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 2, 400.0, order=1),
        t(2, "2026-10-02", "Sell to Open", C175, 1, 150.0, order=2),
        t(3, "2026-10-03", "Buy to Close", C175, 2, -100.0, order=3),
    ])
    first, second = by_id(j)["order-1"], by_id(j)["order-2"]
    assert (first.status, first.realized) == ("closed", pytest.approx(300.0))
    assert (second.status, second.realized) == ("open", None)
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 2, 400.0, order=1),
        t(3, "2026-10-03", "Buy to Close", C175, 1, -50.0, order=3),
    ])
    (only,) = j.positions
    assert (only.status, only.realized) == ("partly_closed", pytest.approx(150.0))  # half the credit, less the close
    assert only.legs[0].quantity == -2 and only.legs[0].closed == 1


def test_a_close_with_nothing_open_is_listed_not_guessed() -> None:
    j = tj.build_journal([t(1, "2026-10-03", "Buy to Close", C175, 1, -100.0, order=3)])
    assert j.positions == []
    (row,) = j.unmatched
    assert row.id == 1 and "nothing open" in row.reason


def test_a_reversed_trade_and_its_reversal_leave_the_matching() -> None:
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 1, 480.0, order=10),
        t(2, "2026-10-01", "Buy to Close", C175, 1, -480.0, reverses=1),
    ])
    assert j.positions == [] and j.unmatched == []


def test_after_a_split_the_p_and_l_is_not_computed() -> None:
    j = tj.build_journal([
        t(1, "2026-06-01", "Buy to Open", "NVDA", 10, -1000.0, order=1),
        t(2, "2026-06-10", None, "NVDA", 90, None, sub="Forward Split", kind="Receive Deliver"),
        t(3, "2026-07-01", "Sell to Close", "NVDA", 10, 200.0, order=2),
    ])
    (p,) = j.positions
    assert p.realized is None and p.note is not None and "split" in p.note.lower()
    assert [r.reason for r in j.unmatched] == ["not modelled: Forward Split"]


def test_a_close_that_spans_two_positions_splits_its_fees() -> None:
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 1, 200.0, order=1, fees=1.0),
        t(2, "2026-10-02", "Sell to Open", C175, 1, 200.0, order=2, fees=1.0),
        t(3, "2026-10-03", "Buy to Close", C175, 2, -100.0, order=3, fees=2.0),
    ])
    assert [p.fees for p in j.positions] == [pytest.approx(2.0), pytest.approx(2.0)]
    assert j.totals.fees == pytest.approx(4.0)


def test_months_and_underlyings_take_the_close() -> None:
    spy = occ("2026-12-18", "P", 600, root="SPY")
    j = tj.build_journal([
        t(1, "2026-10-20", "Sell to Open", C175, 1, 300.0, order=1),
        t(2, "2026-11-05", "Buy to Close", C175, 1, -100.0, order=2),
        t(3, "2026-11-06", "Buy to Open", spy, 1, -500.0, order=3, underlying="SPY"),
        t(4, "2026-12-01", "Sell to Close", spy, 1, 350.0, order=4, underlying="SPY"),
    ])
    assert [(m.month, m.realized) for m in j.months] == [("2026-11", pytest.approx(200.0)), ("2026-12", pytest.approx(-150.0))]
    assert {u.underlying: u.realized for u in j.underlyings} == {"NVDA": pytest.approx(200.0), "SPY": pytest.approx(-150.0)}
    assert (j.totals.closed, j.totals.profitable) == (2, 1)


def test_a_roll_links_the_two_positions() -> None:
    jan = occ("2027-01-15", "C", 180)
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 1, 300.0, order=1),
        t(2, "2026-12-10", "Buy to Close", C175, 1, -250.0, order=2),
        t(3, "2026-12-10", "Sell to Open", jan, 1, 400.0, order=2),
    ])
    old, new = by_id(j)["order-1"], by_id(j)["order-2"]
    assert old.rolled_to == "order-2" and new.rolled_from == "order-1"
    assert (old.realized, new.status) == (pytest.approx(50.0), "open")


def test_an_option_symbol_that_does_not_parse_is_listed() -> None:
    j = tj.build_journal([t(1, "2026-10-01", "Sell to Open", "NVDA 261218C175", 1, 300.0, order=1)])
    assert j.positions == [] and "not a contract" in j.unmatched[0].reason


def test_money_movements_are_not_positions() -> None:
    j = tj.build_journal([t(1, "2026-10-01", None, None, None, 5000.0, kind="Money Movement", sub="Deposit")])
    assert j.positions == [] and j.unmatched == []


@pytest.mark.parametrize(
    ("legs", "cash", "name"),
    [
        ([("C", "2026-12-18", 175, 1)], -300.0, "long call"),
        ([("P", "2026-12-18", 150, -1)], 200.0, "short put"),
        ([("P", "2026-12-18", 150, 1), ("P", "2026-12-18", 160, -1)], 300.0, "put vertical, credit"),
        ([("C", "2026-12-18", 175, -1), ("C", "2027-01-15", 175, 1)], -100.0, "call calendar"),
        ([("C", "2026-12-18", 175, -1), ("C", "2027-01-15", 180, 1)], -100.0, "call diagonal"),
        ([("C", "2026-12-18", 175, -1), ("P", "2026-12-18", 175, -1)], 900.0, "short straddle"),
        ([("C", "2026-12-18", 190, 1), ("P", "2026-12-18", 150, 1)], -400.0, "long strangle"),
        ([("P", "2026-12-18", 160, 1), ("P", "2026-12-18", 175, -1), ("C", "2026-12-18", 175, -1), ("C", "2026-12-18", 190, 1)], 900.0, "iron butterfly, credit"),
        ([("C", "2026-12-18", 170, 1), ("C", "2026-12-18", 175, -2), ("C", "2026-12-18", 180, 1)], -50.0, "call butterfly"),
        ([("C", "2026-12-18", 170, 1), ("C", "2026-12-18", 175, 1), ("P", "2026-12-18", 150, -1)], -50.0, "custom, 3 legs"),
    ],
)
def test_the_structure_is_named_from_the_legs(legs: list[tuple[str, str, float, int]], cash: float, name: str) -> None:
    rows = [
        t(i, "2026-10-01", "Buy to Open" if q > 0 else "Sell to Open", occ(e, k, s), abs(q), cash if i == 1 else 0.0, order=1)
        for i, (k, e, s, q) in enumerate(legs, start=1)
    ]
    (p,) = tj.build_journal(rows).positions
    assert p.structure == name


def test_stock_and_a_call_sold_in_one_order_is_a_covered_call() -> None:
    (p,) = tj.build_journal([
        t(1, "2026-10-01", "Buy to Open", "NVDA", 100, -15000.0, order=1),
        t(2, "2026-10-01", "Sell to Open", C175, 1, 300.0, order=1),
    ]).positions
    assert p.structure == "covered call"


def test_a_closed_position_without_a_p_and_l_isnt_counted_as_a_loss() -> None:
    """After a split the P&L isn't computed: the position is counted apart,
    not as closed at 0 (#131's AI review)."""
    j = tj.build_journal([
        t(1, "2026-06-01", "Buy to Open", "NVDA", 10, -1000.0, order=1),
        t(2, "2026-06-10", None, "NVDA", 90, None, sub="Forward Split", kind="Receive Deliver"),
        t(3, "2026-07-01", "Sell to Close", "NVDA", 10, 200.0, order=2),
        t(4, "2026-07-02", "Sell to Open", C175, 1, 300.0, order=3),
        t(5, "2026-07-03", "Buy to Close", C175, 1, -100.0, order=4),
    ])
    assert (j.totals.closed, j.totals.profitable, j.totals.unpriced) == (1, 1, 1)
    assert j.totals.realized == pytest.approx(200.0)


def test_the_fees_beside_the_realized_p_and_l_are_the_closed_parts_own() -> None:
    """Fees of a position still open aren't in the figure realized
    (#131's AI review)."""
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 2, 400.0, order=1, fees=2.0),
        t(2, "2026-10-02", "Buy to Close", C175, 1, -50.0, order=2, fees=1.0),
        t(3, "2026-10-03", "Buy to Open", occ("2026-12-18", "P", 150), 1, -300.0, order=3, fees=1.0),
    ])
    assert j.totals.fees == pytest.approx(1.0 + 1.0)  # half the open's fees, all the close's
    assert j.totals.realized == pytest.approx(150.0)


def test_stock_delivered_a_day_later_still_links_to_its_option() -> None:
    p150 = occ("2026-11-20", "P", 150)
    j = tj.build_journal([
        t(1, "2026-11-01", "Sell to Open", p150, 1, 300.0, order=30),
        t(2, "2026-11-20", "Buy to Close", p150, 1, 0.0, sub="Assignment", kind="Receive Deliver"),
        t(3, "2026-11-23", "Buy to Open", "NVDA", 100, -15000.0, sub="Assignment", kind="Receive Deliver"),
    ])
    (stock,) = (p for p in j.positions if p.structure == "stock")
    assert stock.origin_position == "order-30"


def test_a_close_reaches_the_lot_it_closes_wherever_it_is_queued() -> None:
    """Long and short lots of one contract (not something tastytrade nets
    away in every account type): a buy to close finds the short one."""
    j = tj.build_journal([
        t(1, "2026-10-01", "Buy to Open", C175, 1, -300.0, order=1),
        t(2, "2026-10-02", "Sell to Open", C175, 1, 290.0, order=2),
        t(3, "2026-10-03", "Buy to Close", C175, 1, -250.0, order=3),
    ])
    assert j.unmatched == []
    short = next(p for p in j.positions if p.id == "order-2")
    assert (short.status, short.realized) == ("closed", pytest.approx(40.0))


def test_a_close_bigger_than_what_is_open_lists_only_the_rest() -> None:
    """Three closed, two with nothing to close: the two are listed, and say
    so (#131's second AI review)."""
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 3, 900.0, order=1),
        t(2, "2026-10-02", "Buy to Close", C175, 5, -500.0, order=2),
    ])
    (p,) = j.positions
    assert (p.status, p.realized) == ("closed", pytest.approx(600.0))
    (row,) = j.unmatched
    assert row.reason.startswith("2 of 5 had nothing open to close")


def test_an_expiry_without_a_buy_or_sell_still_closes_the_option() -> None:
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 1, 300.0, order=1),
        t(2, "2026-12-18", None, C175, 1, 0.0, sub="Expiration", kind="Receive Deliver"),
    ])
    (p,) = j.positions
    assert (p.status, p.ended_by, p.realized) == ("closed", "expired", pytest.approx(300.0))
    assert j.unmatched == []


def test_the_totals_say_what_partly_closed_positions_add() -> None:
    """The realized figure includes partial closes: the count of partly
    closed positions goes with it (#131's second AI review)."""
    j = tj.build_journal([
        t(1, "2026-10-01", "Sell to Open", C175, 2, 400.0, order=1),
        t(2, "2026-10-02", "Buy to Close", C175, 1, -50.0, order=2),
    ])
    assert (j.totals.closed, j.totals.partly, j.totals.realized) == (0, 1, pytest.approx(150.0))
    (p,) = j.positions
    assert p.closed_at is None  # not closed yet: only the last close of a part

