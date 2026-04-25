"""
Tests for parse_form_4_cluster. fetch_edgar is mocked at the
module-import boundary (the symbol that ``form_4.py`` imported), so
none of these hit the SEC. The XML parser is also exercised directly
with sample XML so the math is provable from a known-good fixture.

What we're pinning:

1. Aggregation math — buys / sells / awards / exercises sum into the
   right buckets; A / M / F / G are counted as transactions but never
   move the buy/sell needle.
2. Distinct filer counting — same person across multiple filings
   counts once.
3. Date-range provenance — first_filing_date ≤ last_filing_date,
   sourced from EdgarFiling.filed_at, not from the XML.
4. Resilience — malformed XML in one filing is skipped, the rest are
   still parsed; missing primary_doc_text is also skipped.
5. Stable shape — empty filings list still emits all 10 claim keys
   with None values.
6. Observability — single log_external_call with parsed/skipped counts.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.edgar import EdgarFiling
from app.schemas.research import Claim
from app.services import form_4 as form_4_module
from app.services.form_4 import (
    CLAIM_KEYS,
    _parse_form_4_xml,
    parse_form_4_cluster,
)


def _form_4_xml(
    *,
    owner_cik: str = "0001234567",
    owner_name: str = "DOE JOHN",
    transactions: list[dict[str, Any]] | None = None,
) -> str:
    """Build a minimal-but-valid Form 4 XML for tests."""
    transactions = transactions or []
    txns_xml = "\n".join(
        f"""<nonDerivativeTransaction>
            <transactionDate><value>{t['date']}</value></transactionDate>
            <transactionCoding><transactionCode>{t['code']}</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{t['shares']}</value></transactionShares>
                <transactionPricePerShare><value>{t.get('price', 0)}</value></transactionPricePerShare>
            </transactionAmounts>
        </nonDerivativeTransaction>"""
        for t in transactions
    )
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>{owner_cik}</rptOwnerCik>
            <rptOwnerName>{owner_name}</rptOwnerName>
        </reportingOwnerId>
    </reportingOwner>
    <nonDerivativeTable>
        {txns_xml}
    </nonDerivativeTable>
</ownershipDocument>"""


def _mk_filing(
    *,
    accession: str,
    filed_at: datetime,
    primary_doc_text: str | None,
) -> EdgarFiling:
    return EdgarFiling(
        cik="0000320193",
        symbol="AAPL",
        accession=accession,
        form_type="4",
        filed_at=filed_at,
        period_of_report=filed_at.date(),
        primary_doc_url=f"https://www.sec.gov/Archives/edgar/data/320193/{accession.replace('-', '')}/wf-form4.xml",
        primary_doc_text=primary_doc_text,
        size_bytes=len(primary_doc_text or ""),
    )


def _patch_fetch_edgar(
    monkeypatch: pytest.MonkeyPatch,
    filings: list[EdgarFiling] | Exception,
) -> None:
    """Replace the fetch_edgar symbol form_4.py imported at module load."""

    async def _fake_fetch_edgar(*_a: Any, **_kw: Any) -> list[EdgarFiling]:
        if isinstance(filings, Exception):
            raise filings
        return filings

    monkeypatch.setattr(form_4_module, "fetch_edgar", _fake_fetch_edgar)


# ── XML parser unit tests ─────────────────────────────────────────────


def test_xml_parser_extracts_owner_and_one_transaction() -> None:
    xml = _form_4_xml(
        owner_cik="0001214156",
        owner_name="COOK TIMOTHY D",
        transactions=[
            {"date": "2024-10-15", "code": "S", "shares": 50_000, "price": 235.00}
        ],
    )

    txns = _parse_form_4_xml(xml)

    assert len(txns) == 1
    t = txns[0]
    assert t.owner_cik == "0001214156"
    assert t.owner_name == "COOK TIMOTHY D"
    assert t.date == "2024-10-15"
    assert t.code == "S"
    assert t.shares == 50_000
    assert t.price == 235.00


def test_xml_parser_handles_multiple_transactions_in_one_filing() -> None:
    xml = _form_4_xml(
        transactions=[
            {"date": "2024-10-15", "code": "P", "shares": 1000, "price": 100.0},
            {"date": "2024-10-15", "code": "P", "shares": 500, "price": 101.0},
            {"date": "2024-10-15", "code": "A", "shares": 2000, "price": 0},
        ],
    )

    txns = _parse_form_4_xml(xml)

    assert len(txns) == 3
    assert [t.code for t in txns] == ["P", "P", "A"]


def test_xml_parser_returns_empty_when_no_transactions() -> None:
    xml = _form_4_xml(transactions=[])

    txns = _parse_form_4_xml(xml)

    assert txns == []


def test_xml_parser_raises_on_malformed_xml() -> None:
    """Pure parser raises; the async entry point catches and skips."""
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        _parse_form_4_xml("<not valid xml")


# ── async entry point — aggregation ───────────────────────────────────


async def test_emits_all_claim_keys_with_stable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fetch_edgar(monkeypatch, [])

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert set(result.keys()) == set(CLAIM_KEYS)
    for claim in result.values():
        assert isinstance(claim, Claim)


async def test_empty_filings_list_yields_all_none_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fetch_edgar(monkeypatch, [])

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    for key in CLAIM_KEYS:
        assert result[key].value is None, f"expected None for {key}"


async def test_buy_only_filings_populate_only_buy_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                owner_cik="0001000001",
                owner_name="ALICE",
                transactions=[
                    {"date": "2024-10-15", "code": "P", "shares": 1000, "price": 100.0}
                ],
            ),
        ),
        _mk_filing(
            accession="0000320193-24-000101",
            filed_at=datetime(2024, 10, 16, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                owner_cik="0001000002",
                owner_name="BOB",
                transactions=[
                    {"date": "2024-10-16", "code": "P", "shares": 500, "price": 102.0}
                ],
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.shares_bought"].value == 1500
    assert result["cluster.shares_sold"].value == 0
    assert result["cluster.dollar_bought"].value == pytest.approx(
        1000 * 100.0 + 500 * 102.0
    )
    assert result["cluster.dollar_sold"].value == 0
    assert result["cluster.net_shares"].value == 1500
    assert result["cluster.net_dollars"].value == pytest.approx(151_000.0)


async def test_sell_only_filings_populate_only_sell_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[
                    {"date": "2024-10-15", "code": "S", "shares": 5000, "price": 200.0}
                ],
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.shares_bought"].value == 0
    assert result["cluster.shares_sold"].value == 5000
    assert result["cluster.dollar_sold"].value == pytest.approx(1_000_000.0)
    assert result["cluster.net_shares"].value == -5000


async def test_mixed_transactions_aggregate_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                owner_cik="0001000001",
                owner_name="ALICE",
                transactions=[
                    {"date": "2024-10-15", "code": "P", "shares": 1000, "price": 100.0},
                    {"date": "2024-10-15", "code": "S", "shares": 200, "price": 105.0},
                ],
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.shares_bought"].value == 1000
    assert result["cluster.shares_sold"].value == 200
    assert result["cluster.net_shares"].value == 800
    assert result["cluster.transaction_count"].value == 2


async def test_award_exercise_tax_codes_count_as_transactions_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A / M / F / G never move buy/sell aggregates — those are accounting noise."""
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[
                    {"date": "2024-10-15", "code": "A", "shares": 10_000, "price": 0},
                    {"date": "2024-10-15", "code": "M", "shares": 5_000, "price": 50.0},
                    {"date": "2024-10-15", "code": "F", "shares": 2_000, "price": 235.0},
                    {"date": "2024-10-15", "code": "G", "shares": 1_000, "price": 0},
                ],
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.shares_bought"].value == 0
    assert result["cluster.shares_sold"].value == 0
    assert result["cluster.transaction_count"].value == 4


async def test_distinct_filer_count_dedupes_same_owner_across_filings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                owner_cik="0001000001",
                owner_name="ALICE",
                transactions=[{"date": "2024-10-15", "code": "P", "shares": 100, "price": 100}],
            ),
        ),
        _mk_filing(
            accession="0000320193-24-000101",
            filed_at=datetime(2024, 10, 16, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                owner_cik="0001000001",
                owner_name="ALICE",
                transactions=[{"date": "2024-10-16", "code": "S", "shares": 50, "price": 105}],
            ),
        ),
        _mk_filing(
            accession="0000320193-24-000102",
            filed_at=datetime(2024, 10, 17, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                owner_cik="0001000002",
                owner_name="BOB",
                transactions=[{"date": "2024-10-17", "code": "P", "shares": 200, "price": 100}],
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.filer_count"].value == 2  # ALICE + BOB, dedupedalice
    assert result["cluster.transaction_count"].value == 3


async def test_date_range_taken_from_filing_filed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-10-15", "code": "P", "shares": 100, "price": 100}]
            ),
        ),
        _mk_filing(
            accession="0000320193-24-000099",
            filed_at=datetime(2024, 9, 1, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-09-01", "code": "P", "shares": 200, "price": 100}]
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.first_filing_date"].value == "2024-09-01"
    assert result["cluster.last_filing_date"].value == "2024-10-15"


async def test_malformed_xml_is_skipped_others_still_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text="<not valid xml",
        ),
        _mk_filing(
            accession="0000320193-24-000101",
            filed_at=datetime(2024, 10, 16, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-10-16", "code": "P", "shares": 1000, "price": 100}]
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    # The good filing is still aggregated.
    assert result["cluster.shares_bought"].value == 1000
    assert result["cluster.transaction_count"].value == 1


async def test_missing_primary_doc_text_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filing that came back from fetch_edgar without text isn't parseable."""
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=None,
        ),
        _mk_filing(
            accession="0000320193-24-000101",
            filed_at=datetime(2024, 10, 16, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-10-16", "code": "P", "shares": 1000, "price": 100}]
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster("AAPL", recent_n=10)

    assert result["cluster.shares_bought"].value == 1000


# ── provenance + observability ────────────────────────────────────────


async def test_claims_carry_provider_scoped_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-10-15", "code": "P", "shares": 100, "price": 100}]
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    result = await parse_form_4_cluster(
        "AAPL", recent_n=10, edgar_provider="sec"
    )

    bought = result["cluster.shares_bought"]
    assert bought.source.tool == "sec.form_4"
    assert "form 4 filings" in bought.source.detail.lower()
    assert "2024-10-15" in bought.source.detail


async def test_logs_one_external_call_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-10-15", "code": "P", "shares": 100, "price": 100}]
            ),
        ),
        _mk_filing(
            accession="0000320193-24-000101",
            filed_at=datetime(2024, 10, 16, tzinfo=UTC),
            primary_doc_text="<broken xml",  # parsed_count drops by 1
        ),
        _mk_filing(
            accession="0000320193-24-000102",
            filed_at=datetime(2024, 10, 17, tzinfo=UTC),
            primary_doc_text=None,  # also skipped
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    with caplog.at_level(logging.INFO, logger="app.external"):
        await parse_form_4_cluster(
            "AAPL", recent_n=10, edgar_provider="sec"
        )

    records = [r for r in caplog.records if r.name == "app.external"]
    # fetch_edgar's own log_external_call won't fire — we mocked it out —
    # so we expect exactly one record from form_4's wrapper.
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "sec.form_4"
    assert r.input_summary == {
        "symbol": "AAPL",
        "recent_n": 10,
        "edgar_provider": "sec",
    }
    assert r.output_summary["filing_count"] == 3
    assert r.output_summary["parsed_count"] == 1
    assert r.output_summary["skipped_count"] == 2
    assert r.output_summary["transaction_count"] == 1
    assert r.outcome == "ok"


async def test_fetch_edgar_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    _patch_fetch_edgar(monkeypatch, RuntimeError("EDGAR is down"))

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="EDGAR is down"):
            await parse_form_4_cluster("AAPL", recent_n=10)

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


async def test_symbol_uppercased_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_symbols: list[str] = []

    async def _capture(symbol: str, **_kw: Any) -> list[EdgarFiling]:
        seen_symbols.append(symbol)
        return []

    monkeypatch.setattr(form_4_module, "fetch_edgar", _capture)

    await parse_form_4_cluster("aapl", recent_n=10)

    assert seen_symbols == ["AAPL"]


async def test_fetched_at_is_fresh_and_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    filings = [
        _mk_filing(
            accession="0000320193-24-000100",
            filed_at=datetime(2024, 10, 15, tzinfo=UTC),
            primary_doc_text=_form_4_xml(
                transactions=[{"date": "2024-10-15", "code": "P", "shares": 100, "price": 100}]
            ),
        ),
    ]
    _patch_fetch_edgar(monkeypatch, filings)

    before = datetime.now(UTC)
    result = await parse_form_4_cluster("AAPL", recent_n=10)
    after = datetime.now(UTC)

    fetched = result["cluster.shares_bought"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched <= after + timedelta(seconds=1)
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1
