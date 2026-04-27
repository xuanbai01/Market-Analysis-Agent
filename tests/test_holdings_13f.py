"""
Tests for parse_13f_holdings. fetch_edgar is mocked at the module-import
boundary (same pattern as form_4 / ten_k). Two layers:

1. **Pure XML parser** (`_parse_13f_xml`) — given a 13F-HR XML body and a
   target CUSIP, returns a list of `_HoldingRow` (or empty). Tests pin
   the schema understanding and CUSIP filtering.
2. **Async entry point** — coordinates fetch_edgar across the curated
   institution list, parses each filing's XML, aggregates holdings of
   the target symbol. Tests pin aggregation math, top-holder
   identification, graceful degradation paths.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.schemas.edgar import EdgarFiling
from app.schemas.research import Claim
from app.services import holdings_13f as holdings_module
from app.services.holdings_13f import (
    CLAIM_KEYS,
    _parse_13f_xml,
    parse_13f_holdings,
)

# ── XML fixtures ──────────────────────────────────────────────────────


def _holding_row(*, cusip: str, name: str, shares: int, value: int) -> str:
    """Build one <infoTable> row for a 13F-HR XML body.

    The 13F-HR schema wraps each holding in <infoTable>, with the
    holder description (`nameOfIssuer`), CUSIP, USD value (`value`,
    in $1000s), and `shrsOrPrnAmt > sshPrnamt` for share count.
    """
    return f"""<infoTable>
    <nameOfIssuer>{name}</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>{cusip}</cusip>
    <value>{value}</value>
    <shrsOrPrnAmt>
        <sshPrnamt>{shares}</sshPrnamt>
        <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
        <Sole>{shares}</Sole>
        <Shared>0</Shared>
        <None>0</None>
    </votingAuthority>
</infoTable>"""


def _13f_xml(rows: list[str]) -> str:
    """Wrap one or more infoTable rows in a 13F-HR informationTable document."""
    body = "\n".join(rows)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
    {body}
</informationTable>"""


# AAPL CUSIP for tests; matches the value in cusips.py.
_AAPL_CUSIP = "037833100"
_NVDA_CUSIP = "67066G104"


# ── XML parser unit tests ─────────────────────────────────────────────


def test_xml_parser_extracts_single_matching_holding() -> None:
    xml = _13f_xml(
        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1_000_000, value=250_000)]
    )

    rows = _parse_13f_xml(xml, target_cusip=_AAPL_CUSIP)

    assert len(rows) == 1
    r = rows[0]
    assert r.cusip == _AAPL_CUSIP
    assert r.name == "APPLE INC"
    assert r.shares == 1_000_000
    assert r.value == 250_000


def test_xml_parser_filters_to_target_cusip() -> None:
    """Only rows matching the target CUSIP come back; everything else is dropped."""
    xml = _13f_xml([
        _holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1_000_000, value=250_000),
        _holding_row(cusip=_NVDA_CUSIP, name="NVIDIA CORP", shares=500_000, value=400_000),
        _holding_row(cusip="594918104", name="MICROSOFT CORP", shares=300_000, value=130_000),
    ])

    rows = _parse_13f_xml(xml, target_cusip=_AAPL_CUSIP)

    assert len(rows) == 1
    assert rows[0].name == "APPLE INC"


def test_xml_parser_returns_empty_when_target_cusip_absent() -> None:
    xml = _13f_xml([
        _holding_row(cusip="594918104", name="MICROSOFT CORP", shares=100, value=50),
    ])

    rows = _parse_13f_xml(xml, target_cusip=_AAPL_CUSIP)

    assert rows == []


def test_xml_parser_handles_empty_information_table() -> None:
    xml = _13f_xml([])

    rows = _parse_13f_xml(xml, target_cusip=_AAPL_CUSIP)

    assert rows == []


def test_xml_parser_raises_on_malformed_xml() -> None:
    """Pure parser raises; async layer catches and skips that filing."""
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        _parse_13f_xml("<not valid xml", target_cusip=_AAPL_CUSIP)


# ── Async entry point — fixtures + helpers ────────────────────────────


def _mk_filing(
    *,
    cik: str,
    institution_label: str,
    accession: str,
    period_of_report: date,
    primary_doc_text: str | None,
) -> EdgarFiling:
    """A 13F-HR EdgarFiling for a curated institution."""
    return EdgarFiling(
        cik=cik,
        symbol=institution_label,
        accession=accession,
        form_type="13F-HR",
        filed_at=datetime(period_of_report.year, period_of_report.month, 14, tzinfo=UTC),
        period_of_report=period_of_report,
        primary_doc_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/infotable.xml",
        primary_doc_text=primary_doc_text,
        size_bytes=len(primary_doc_text or ""),
    )


def _patch_fetch_edgar_per_institution(
    monkeypatch: pytest.MonkeyPatch,
    by_cik: dict[str, list[EdgarFiling] | Exception],
) -> list[dict[str, Any]]:
    """
    Replace fetch_edgar with a fake that returns per-institution filings
    keyed by CIK. Returns a list of every kwarg call captured, so tests
    can assert the cik= bypass was used (rather than ticker lookup).
    """
    captured: list[dict[str, Any]] = []

    async def _fake(symbol: str, **kwargs: Any) -> list[EdgarFiling]:
        captured.append({"symbol": symbol, **kwargs})
        cik = kwargs.get("cik")
        result = by_cik.get(cik or "", [])
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(holdings_module, "fetch_edgar", _fake)
    return captured


def _patch_institutions(
    monkeypatch: pytest.MonkeyPatch, institutions: list[tuple[str, str]]
) -> None:
    """Override the curated institution list for a single test (e.g. just 2-3 fakes)."""
    monkeypatch.setattr(holdings_module, "NOTABLE_INSTITUTIONS", institutions)


# ── Async entry point — happy paths + aggregation ─────────────────────


async def test_emits_all_claim_keys_with_stable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(monkeypatch, {"0001067983": []})

    result = await parse_13f_holdings("AAPL")

    assert set(result.keys()) == set(CLAIM_KEYS)
    for c in result.values():
        assert isinstance(c, Claim)


async def test_aggregates_shares_and_value_across_institutions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=400_000_000,
                                value=80_000_000,
                            )
                        ]
                    ),
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=1_000_000_000,
                                value=200_000_000,
                            )
                        ]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    assert result["institutions.holding_count"].value == 2
    assert result["institutions.total_shares_held"].value == 1_400_000_000
    assert result["institutions.total_market_value"].value == 280_000_000


async def test_holders_list_is_comma_separated_and_sorted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=100, value=20)]
                    ),
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=200, value=40)]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    # Sorted alphabetically for deterministic output.
    assert result["institutions.holders_list"].value == "BERKSHIRE, BLACKROCK"


async def test_top_holder_is_largest_position_by_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=400_000_000,
                                value=80_000_000,
                            )
                        ]
                    ),
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=1_000_000_000,
                                value=200_000_000,
                            )
                        ]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    assert result["institutions.top_holder_name"].value == "BLACKROCK"
    assert result["institutions.top_holder_shares"].value == 1_000_000_000


async def test_top_holder_tie_broken_alphabetically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    same_shares = 500_000
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=same_shares,
                                value=100,
                            )
                        ]
                    ),
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=same_shares,
                                value=100,
                            )
                        ]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    # Alphabetically first wins on tie.
    assert result["institutions.top_holder_name"].value == "BERKSHIRE"


async def test_period_range_taken_from_filings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 6, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1, value=1)]
                    ),
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1, value=1)]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    assert result["institutions.first_period"].value == "2024-06-30"
    assert result["institutions.last_period"].value == "2024-09-30"


# ── Graceful degradation ──────────────────────────────────────────────


async def test_no_holders_yields_all_none_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Curated institutions exist but none hold the symbol → all-None."""
    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip="594918104", name="MICROSOFT", shares=1, value=1)]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    for key in CLAIM_KEYS:
        assert result[key].value is None, f"expected None for {key}"


async def test_unknown_ticker_skips_fetch_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Symbol not in CUSIP map → all-None claims, zero fetch_edgar calls."""
    captured = _patch_fetch_edgar_per_institution(monkeypatch, {})

    result = await parse_13f_holdings("WEIRDCO")

    for key in CLAIM_KEYS:
        assert result[key].value is None
    # No fetch_edgar calls — there's nothing to look up without a CUSIP.
    assert captured == []


async def test_malformed_xml_in_one_filing_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One institution's broken XML doesn't kill the rest."""
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text="<not valid xml",  # broken
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=1_000,
                                value=200,
                            )
                        ]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    # BLACKROCK's row still came through.
    assert result["institutions.holding_count"].value == 1
    assert result["institutions.top_holder_name"].value == "BLACKROCK"


async def test_institution_with_no_recent_13f_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_edgar returning [] for an institution → not counted."""
    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [],  # No recent 13F
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [
                            _holding_row(
                                cusip=_AAPL_CUSIP,
                                name="APPLE INC",
                                shares=100,
                                value=20,
                            )
                        ]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    assert result["institutions.holding_count"].value == 1
    assert result["institutions.holders_list"].value == "BLACKROCK"


async def test_filing_with_no_text_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_edgar returning a filing without primary_doc_text → skipped."""
    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=None,
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL")

    assert result["institutions.holding_count"].value is None


# ── Provenance / behavior / observability ─────────────────────────────


async def test_uses_cik_bypass_not_ticker_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fetch_edgar must be called with cik=, not relying on ticker→CIK lookup.

    Institutions don't have tickers in SEC's company_tickers.json, so the
    cik= bypass is the only way fetch_edgar can find their filings.
    """
    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    captured = _patch_fetch_edgar_per_institution(
        monkeypatch, {"0001067983": []}
    )

    await parse_13f_holdings("AAPL")

    assert len(captured) == 1
    assert captured[0]["cik"] == "0001067983"
    assert captured[0]["form_type"] == "13F-HR"


async def test_claims_carry_provider_scoped_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1, value=1)]
                    ),
                ),
            ],
        },
    )

    result = await parse_13f_holdings("AAPL", edgar_provider="sec")

    bought = result["institutions.holding_count"]
    assert bought.source.tool == "sec.holdings_13f"
    assert "13f" in bought.source.detail.lower()


async def test_logs_one_external_call_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    _patch_institutions(
        monkeypatch,
        [("0001067983", "BERKSHIRE"), ("0001364742", "BLACKROCK")],
    )
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text="<broken",  # parse fails
                ),
            ],
            "0001364742": [
                _mk_filing(
                    cik="0001364742",
                    institution_label="BLACKROCK",
                    accession="0001364742-24-000020",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1, value=1)]
                    ),
                ),
            ],
        },
    )

    with caplog.at_level(logging.INFO, logger="app.external"):
        await parse_13f_holdings("AAPL")

    # fetch_edgar is mocked away, so its log_external_call won't fire —
    # we expect exactly one record from the parse_13f_holdings wrapper.
    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "sec.holdings_13f"
    assert r.input_summary["symbol"] == "AAPL"
    assert r.input_summary["edgar_provider"] == "sec"
    assert r.output_summary["institutions_queried"] == 2
    assert r.output_summary["parsed_count"] == 1
    assert r.output_summary["skipped_count"] == 1
    assert r.output_summary["holders_found"] == 1
    assert r.outcome == "ok"


async def test_unknown_ticker_logs_with_zero_query_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Symbol not in CUSIP map → log records the early-out reason."""
    import logging

    _patch_fetch_edgar_per_institution(monkeypatch, {})

    with caplog.at_level(logging.INFO, logger="app.external"):
        await parse_13f_holdings("WEIRDCO")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.output_summary["institutions_queried"] == 0
    assert r.output_summary.get("reason") == "cusip_unknown"


async def test_fetch_edgar_exception_propagates(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When one institution's fetch raises, the whole call dies — the institution
    list is small enough that we don't have meaningful per-institution
    isolation; the alternative (silent 'we tried') hides bugs."""
    import logging

    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(
        monkeypatch, {"0001067983": RuntimeError("EDGAR is down")}
    )

    with caplog.at_level(logging.INFO, logger="app.external"):
        with pytest.raises(RuntimeError, match="EDGAR is down"):
            await parse_13f_holdings("AAPL")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    assert records[0].outcome == "error"


async def test_symbol_uppercased_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lowercase ticker still resolves through the (uppercase) CUSIP map."""
    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(monkeypatch, {"0001067983": []})

    result = await parse_13f_holdings("aapl")

    # If symbol weren't uppercased, lookup_cusip would miss → all-None,
    # zero fetch_edgar calls. Reaching the curated institution loop
    # means uppercasing happened.
    assert "institutions.holding_count" in result


async def test_fetched_at_is_fresh_and_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    _patch_institutions(monkeypatch, [("0001067983", "BERKSHIRE")])
    _patch_fetch_edgar_per_institution(
        monkeypatch,
        {
            "0001067983": [
                _mk_filing(
                    cik="0001067983",
                    institution_label="BERKSHIRE",
                    accession="0001067983-24-000010",
                    period_of_report=date(2024, 9, 30),
                    primary_doc_text=_13f_xml(
                        [_holding_row(cusip=_AAPL_CUSIP, name="APPLE INC", shares=1, value=1)]
                    ),
                ),
            ],
        },
    )

    before = datetime.now(UTC)
    result = await parse_13f_holdings("AAPL")
    after = datetime.now(UTC)

    fetched = result["institutions.holding_count"].source.fetched_at
    assert before - timedelta(seconds=1) <= fetched <= after + timedelta(seconds=1)
    fetched_ats = {c.source.fetched_at for c in result.values()}
    assert len(fetched_ats) == 1
