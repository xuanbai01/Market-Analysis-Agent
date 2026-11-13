"""
Insider activity from Form 4 filings (app/services/form_4.py, 2026-11).

The first look at real filings (tasks/dogfood-2026-11.md #30-#32) found
three ways a naive sum misleads, and these tests pin each one:

- a company's own list holds Form 4s it filed as the owner of *another*
  company (Exxon selling Imperial Oil shares), which must not count;
- a 10% holder's purchase (Volkswagen's $1B into Rivian) is a strategic
  investment, not an officer's conviction, so holders are kept apart;
- sales under pre-arranged 10b5-1 plans are routine, so their share of
  selling is reported.

fetch_edgar is replaced at the module boundary; no test reaches SEC.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.schemas.edgar import EdgarFiling
from app.services import form_4 as f4

TODAY = date(2026, 11, 13)
ISSUER = "0001045810"  # NVDA


def _xml(
    *,
    issuer_cik: str = ISSUER,
    owners: list[dict[str, Any]] | None = None,
    plan: str | None = "0",
    transactions: list[dict[str, Any]] | None = None,
) -> str:
    owners = owners if owners is not None else [{"cik": "0001197647", "name": "HUANG JEN HSUN", "officer": "President and CEO", "director": True}]
    owners_xml = ""
    for o in owners:
        rel = ""
        if o.get("director"):
            rel += "<isDirector>1</isDirector>"
        if o.get("officer"):
            rel += f"<isOfficer>1</isOfficer><officerTitle>{o['officer']}</officerTitle>"
        if o.get("ten_percent"):
            rel += "<isTenPercentOwner>true</isTenPercentOwner>"
        if o.get("other"):
            rel += "<isOther>1</isOther>"
        if o.get("other_text"):
            rel += f"<otherText>{o['other_text']}</otherText>"
        owners_xml += f"""<reportingOwner>
            <reportingOwnerId><rptOwnerCik>{o['cik']}</rptOwnerCik><rptOwnerName>{o['name']}</rptOwnerName></reportingOwnerId>
            <reportingOwnerRelationship>{rel}</reportingOwnerRelationship>
        </reportingOwner>"""
    txns = "".join(
        f"""<nonDerivativeTransaction>
            <transactionDate><value>{t['date']}</value></transactionDate>
            <transactionCoding><transactionCode>{t['code']}</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{t['shares']}</value></transactionShares>
                <transactionPricePerShare><value>{t.get('price', 0)}</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{'A' if t['code'] in ('P', 'A', 'M') else 'D'}</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>"""
        for t in (transactions or [])
    )
    plan_xml = "" if plan is None else f"<aff10b5One>{plan}</aff10b5One>"
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <documentType>4</documentType>
    <issuer><issuerCik>{issuer_cik}</issuerCik><issuerTradingSymbol>NVDA</issuerTradingSymbol></issuer>
    {owners_xml}
    {plan_xml}
    <nonDerivativeTable>{txns}</nonDerivativeTable>
</ownershipDocument>"""


_seq = iter(range(1, 10_000))


def _filing(filed: str, text: str | None, *, cik: str = ISSUER) -> EdgarFiling:
    n = next(_seq)
    accession = f"0001197647-26-{n:06d}"
    return EdgarFiling(
        cik=cik,
        symbol="NVDA",
        accession=accession,
        form_type="4",
        filed_at=datetime.fromisoformat(filed).replace(tzinfo=UTC),
        primary_doc_url=f"https://www.sec.gov/Archives/edgar/data/1045810/{accession.replace('-', '')}/form4.xml",
        primary_doc_text=text,
        size_bytes=len(text or ""),
    )


CEO = {"cik": "0001197647", "name": "HUANG JEN HSUN", "officer": "President and CEO", "director": True}
DIRECTOR = {"cik": "0001000001", "name": "STEVENS MARK A", "director": True}
CFO = {"cik": "0001000002", "name": "KRESS COLETTE", "officer": "EVP and Chief Financial Officer"}
VW = {"cik": "0000000099", "name": "VOLKSWAGEN AG", "ten_percent": True}


# ── Parser ───────────────────────────────────────────────────────────


def test_the_parser_reads_issuer_owner_role_plan_and_transactions() -> None:
    doc = f4.parse_form_4(_xml(plan="1", transactions=[{"date": "2026-09-18", "code": "S", "shares": 1000, "price": 180.5}]))

    assert doc.issuer_cik == ISSUER
    assert (doc.owner_cik, doc.owner_name, doc.role, doc.is_insider) == ("0001197647", "HUANG JEN HSUN", "President and CEO", True)
    assert doc.under_plan is True
    [txn] = doc.transactions
    assert (txn.date, txn.code, txn.shares, txn.price) == ("2026-09-18", "S", 1000.0, 180.5)


@pytest.mark.parametrize(
    ("owner", "role", "insider"),
    [
        (DIRECTOR, "Director", True),
        (CFO, "EVP and Chief Financial Officer", True),
        (VW, "10% owner", False),
        ({"cik": "1", "name": "X", "other": True}, "Other", False),
        # Coca-Cola reports its regional presidents as "other" with a title.
        ({"cik": "2", "name": "PIETRACCI BRUNO", "other": True, "other_text": "Europe OU President"}, "Europe OU President", True),
        ({"cik": "3", "name": "FUND LP", "other": True, "other_text": "Member of 10% owner group"}, "Member of 10% owner group", False),
    ],
)
def test_the_role_names_the_title_and_only_officers_and_directors_are_insiders(
    owner: dict[str, Any], role: str, insider: bool
) -> None:
    doc = f4.parse_form_4(_xml(owners=[owner]))
    assert (doc.role, doc.is_insider) == (role, insider)


@pytest.mark.parametrize(("flag", "expected"), [("1", True), ("true", True), ("0", False), ("false", False), (None, None)])
def test_the_10b5_1_flag_comes_in_several_spellings(flag: str | None, expected: bool | None) -> None:
    assert f4.parse_form_4(_xml(plan=flag)).under_plan is expected


def test_a_joint_filing_is_attributed_to_its_officer_or_director() -> None:
    """A director's family trust may file jointly with the director; the
    trade is the director's, counted once."""
    trust = {"cik": "0000000777", "name": "STEVENS FAMILY TRUST", "other": True}
    doc = f4.parse_form_4(_xml(owners=[trust, DIRECTOR]))
    assert (doc.owner_name, doc.is_insider) == ("STEVENS MARK A", True)


def test_malformed_xml_raises() -> None:
    with pytest.raises(Exception):  # noqa: B017 - any parse error
        f4.parse_form_4("<ownershipDocument><issuer>")


# ── Summary ──────────────────────────────────────────────────────────


def sale(day: str, shares: float, price: float) -> dict[str, Any]:
    return {"date": day, "code": "S", "shares": shares, "price": price}


def buy(day: str, shares: float, price: float) -> dict[str, Any]:
    return {"date": day, "code": "P", "shares": shares, "price": price}


def test_officer_and_director_sales_and_buys_are_summed_with_distinct_people() -> None:
    filings = [
        _filing("2026-09-19", _xml(owners=[CEO], plan="1", transactions=[sale("2026-09-18", 1000, 100), sale("2026-09-18", 500, 100)])),
        _filing("2026-08-02", _xml(owners=[CEO], plan="1", transactions=[sale("2026-08-01", 1000, 100)])),
        _filing("2026-07-10", _xml(owners=[CFO], plan="0", transactions=[sale("2026-07-09", 2000, 100)])),
        _filing("2026-06-01", _xml(owners=[DIRECTOR], plan="0", transactions=[buy("2026-05-30", 100, 90)])),
    ]
    s = f4.summarize(filings, today=TODAY)

    assert s.filing_count == 4
    assert s.sell_dollars == pytest.approx(450_000)
    assert s.seller_count == 2
    assert s.buy_dollars == pytest.approx(9_000)
    assert s.buyer_count == 1
    assert s.net_dollars == pytest.approx(9_000 - 450_000)
    # 250k of the 450k sold was under a plan.
    assert s.plan_sale_share == pytest.approx(250_000 / 450_000)
    assert (s.first_filing_date, s.last_filing_date) == ("2026-06-01", "2026-09-19")


def test_a_form_4_about_another_company_is_left_out() -> None:
    """Exxon files Form 4s as the majority owner of Imperial Oil; those
    sit in Exxon's own list and are not Exxon insiders' trades."""
    filings = [
        _filing("2026-05-21", _xml(issuer_cik="0000049938", owners=[{"cik": "34088", "name": "EXXON MOBIL CORP", "ten_percent": True}], transactions=[sale("2026-05-20", 2_000_000, 138.3)])),
        _filing("2026-06-01", _xml(owners=[CFO], transactions=[sale("2026-05-30", 100, 110)])),
    ]
    s = f4.summarize(filings, today=TODAY)

    assert s.filing_count == 1
    assert s.other_issuer_count == 1
    assert s.sell_dollars == pytest.approx(11_000)
    assert s.holder_sell_dollars == 0


def test_a_10_percent_holders_purchase_is_kept_apart_from_insiders() -> None:
    """Volkswagen's $1B into Rivian is a strategic investment."""
    filings = [
        _filing("2026-07-01", _xml(owners=[VW], transactions=[buy("2026-06-30", 70_000_000, 14.29)])),
        _filing("2026-06-01", _xml(owners=[DIRECTOR], transactions=[buy("2026-05-30", 10_000, 15)])),
    ]
    s = f4.summarize(filings, today=TODAY)

    assert s.buy_dollars == pytest.approx(150_000)
    assert s.buyer_count == 1
    assert s.holder_buy_dollars == pytest.approx(70_000_000 * 14.29)


def test_grants_exercises_withholding_and_gifts_count_as_routine_not_trades() -> None:
    filings = [
        _filing("2026-09-01", _xml(owners=[CFO], transactions=[
            {"date": "2026-08-30", "code": "A", "shares": 5000},
            {"date": "2026-08-30", "code": "M", "shares": 1000},
            {"date": "2026-08-30", "code": "F", "shares": 400, "price": 120},
            {"date": "2026-08-30", "code": "G", "shares": 50},
        ])),
    ]
    s = f4.summarize(filings, today=TODAY)

    assert s.routine_count == 4
    assert (s.buy_dollars, s.sell_dollars, s.buyer_count, s.seller_count) == (0, 0, 0, 0)
    assert s.plan_sale_share is None  # nothing sold


def test_only_the_last_six_months_count() -> None:
    filings = [
        _filing("2026-10-01", _xml(owners=[CEO], transactions=[sale("2026-09-30", 100, 100)])),
        # Filed in the window but for a trade before it (a late filing).
        _filing("2026-06-01", _xml(owners=[CFO], transactions=[sale("2026-03-01", 999, 100)])),
        # Filed before the window.
        _filing("2026-04-01", _xml(owners=[DIRECTOR], transactions=[sale("2026-03-30", 999, 100)])),
    ]
    s = f4.summarize(filings, today=TODAY)

    assert s.filing_count == 2
    assert s.sell_dollars == pytest.approx(10_000)
    assert s.seller_count == 1


def test_the_plan_share_is_unknown_when_no_sale_says_either_way() -> None:
    """Filings before April 2023 have no 10b5-1 box."""
    filings = [_filing("2026-09-01", _xml(owners=[CEO], plan=None, transactions=[sale("2026-08-30", 100, 100)]))]
    assert f4.summarize(filings, today=TODAY).plan_sale_share is None


def test_people_are_ranked_by_dollars_traded_and_capped_at_five() -> None:
    names = ["A", "B", "C", "D", "E", "F"]
    filings = [
        _filing("2026-09-01", _xml(owners=[{"cik": f"00000000{i}", "name": n, "director": True}], transactions=[sale("2026-08-30", 100 * (i + 1), 10)]))
        for i, n in enumerate(names)
    ]
    filings.append(_filing("2026-09-02", _xml(owners=[{"cik": "000000002", "name": "C", "director": True}], transactions=[buy("2026-09-01", 5000, 10)])))
    people = f4.summarize(filings, today=TODAY).people

    assert [p.name for p in people] == ["C", "F", "E", "D", "B"]
    c = people[0]
    assert (c.sold, c.bought, c.net) == (pytest.approx(3000), pytest.approx(50_000), pytest.approx(47_000))
    assert c.role == "Director" and c.is_insider


def test_unreadable_filings_are_skipped_and_counted() -> None:
    filings = [
        _filing("2026-09-01", "<not xml"),
        _filing("2026-09-02", None),
        _filing("2026-09-03", _xml(owners=[CFO], transactions=[sale("2026-09-02", 10, 10)])),
    ]
    s = f4.summarize(filings, today=TODAY)
    assert (s.filing_count, s.skipped_count, s.sell_dollars) == (1, 2, pytest.approx(100))


# ── Tool ─────────────────────────────────────────────────────────────


def _patch_edgar(monkeypatch: pytest.MonkeyPatch, filings: list[EdgarFiling]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _fake(symbol: str, **kwargs: Any) -> list[EdgarFiling]:
        calls.append({"symbol": symbol, **kwargs})
        ordered = sorted(filings, key=lambda f: f.filed_at, reverse=True)[: kwargs["recent_n"]]
        if kwargs.get("include_text"):
            return ordered
        return [f.model_copy(update={"primary_doc_text": None}) for f in ordered]

    monkeypatch.setattr(f4, "fetch_edgar", _fake)
    return calls


async def test_the_tool_lists_filings_then_downloads_only_those_in_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_edgar(monkeypatch, [
        _filing("2026-09-19", _xml(owners=[CEO], plan="1", transactions=[sale("2026-09-18", 1000, 180)])),
        _filing("2026-06-01", _xml(owners=[DIRECTOR], transactions=[buy("2026-05-30", 100, 90)])),
        _filing("2025-01-01", _xml(owners=[CFO], transactions=[sale("2024-12-30", 1, 1)])),
    ])

    claims = await f4.fetch_insider_activity("nvda", today=TODAY)

    assert [(c["symbol"], c["recent_n"], c["include_text"]) for c in calls] == [
        ("NVDA", f4.MAX_FILINGS, False),
        ("NVDA", 2, True),
    ]
    assert claims["sell_dollars"].value == pytest.approx(180_000)
    assert claims["sell_dollars"].unit == "usd"
    assert claims["sell_dollars"].description == "Sales by officers and directors, last 6 months"
    assert claims["filing_count"].value == 2
    assert claims["filing_count"].unit == "count"
    assert claims["plan_sale_share"].value == pytest.approx(1.0)
    assert claims["plan_sale_share"].unit == "fraction"
    assert claims["last_filing_date"].value == "2026-09-19"
    assert claims["sell_dollars"].source.tool == "sec.form_4"
    assert "2 Form 4 filings filed 2026-06-01 to 2026-09-19" in (claims["sell_dollars"].source.detail or "")


async def test_each_of_the_top_people_is_a_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_edgar(monkeypatch, [
        _filing("2026-09-19", _xml(owners=[CEO], transactions=[sale("2026-09-18", 1000, 180)])),
        _filing("2026-07-01", _xml(owners=[VW], transactions=[buy("2026-06-30", 1000, 15)])),
    ])

    claims = await f4.fetch_insider_activity("NVDA", today=TODAY)

    first, second = claims["person.1"], claims["person.2"]
    assert first.description == "HUANG JEN HSUN (President and CEO): net bought (+) or sold (−), last 6 months"
    assert first.value == pytest.approx(-180_000)
    assert first.unit == "usd"
    assert "sold $180,000" in (first.source.detail or "")
    assert second.description == "VOLKSWAGEN AG (10% owner): net bought (+) or sold (−), last 6 months"
    assert "person.3" not in claims


async def test_no_filings_at_all_is_empty_with_a_stable_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """A foreign filer (TSM) files no Form 4s."""
    _patch_edgar(monkeypatch, [])

    claims = await f4.fetch_insider_activity("TSM", today=TODAY)

    assert set(claims) == set(f4.CLAIM_KEYS)
    assert all(c.value is None for c in claims.values())


async def test_filings_but_none_recent_says_so_and_dates_the_last_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_edgar(monkeypatch, [_filing("2026-01-05", _xml(owners=[CFO], transactions=[sale("2026-01-02", 1, 1)]))])

    claims = await f4.fetch_insider_activity("NVDA", today=TODAY)

    assert claims["filing_count"].value == 0
    assert claims["last_filing_date"].value == "2026-01-05"
    assert claims["sell_dollars"].value is None


async def test_one_external_call_record_is_written(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    _patch_edgar(monkeypatch, [_filing("2026-09-19", _xml(owners=[CEO], transactions=[sale("2026-09-18", 1, 1)]))])
    with caplog.at_level(logging.INFO, logger="app.external"):
        await f4.fetch_insider_activity("NVDA", today=TODAY)

    [record] = [r for r in caplog.records if r.name == "app.external"]
    assert record.service_id == "sec.form_4"
    assert record.output_summary["listed"] == 1
    assert record.output_summary["in_window"] == 1
