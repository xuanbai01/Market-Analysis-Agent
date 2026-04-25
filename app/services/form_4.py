"""
Form 4 cluster summary — first parser in the ``parse_filing`` family.

Form 4 is the SEC filing insiders (officers, directors, ≥10% owners)
must file within two business days of buying or selling the company's
stock. The XML schema is structured (unlike 10-K HTML), so this is the
cleanest filing type to parse: the values we want — owner name,
transaction code, shares, price — sit at known XPaths.

The agent doesn't need per-insider detail in a research report. It
needs a *cluster summary*: how many distinct insiders, total shares
bought vs sold, total dollar value bought vs sold, net of both, and
the date range the data spans. That's what this tool returns.

## Why aggregate, not per-insider

Per-insider rows balloon the response size and the LLM context window.
The agent's relevant question is "is there an insider buying cluster
right now?" — that's answered by the aggregate. If the agent later
needs per-insider granularity, it can call a more targeted tool; for
now, ten aggregate claims do the job.

## Why P and S are the only "real" codes

Form 4 transaction codes:

- ``P`` — open-market or private purchase. Real insider conviction.
- ``S`` — open-market or private sale. Real insider exit.
- ``A`` — grant, award. Compensation, not conviction.
- ``M`` — option exercise. Mechanical — the insider exercises options
  often as part of an option-exercise-and-immediate-sell pipeline,
  triggered by vest schedules, not by valuation conviction.
- ``F`` — tax withholding. Pure accounting — shares withheld to cover
  the employer's tax obligation on a vesting event.
- ``G`` — gift. Estate planning, charitable transfer.

Only ``P`` and ``S`` survive into ``shares_bought`` /
``shares_sold``; everything else lands in ``transaction_count`` so
we can show "12 transactions, but 0 actual buys and 0 actual sales —
just RSU mechanics" in the cluster summary.

## Test seam

``fetch_edgar`` is imported at module load and re-bound in tests via
``monkeypatch.setattr(form_4_module, "fetch_edgar", ...)``. This
isolates form_4's logic from EDGAR HTTP, the disk cache, and the SEC
rate limit; the parsing math is what we're testing here, not those.

## Excluded for v1

- Derivative transactions (``<derivativeTable>``). Stock options /
  warrants / RSUs reported here. Adds a different math layer
  (notional vs delta-adjusted). Defer until the agent demonstrably
  asks for it.
- Window-based filtering by date. ``recent_n`` is the proxy; if the
  agent wants "last 30 days" it can pass a smaller ``recent_n``. A
  date filter would need a second query path through fetch_edgar.
- Per-insider breakdown. See the rationale above.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.observability import log_external_call
from app.schemas.edgar import EdgarFiling
from app.schemas.research import Claim, ClaimValue, Source
from app.services.edgar import fetch_edgar

# ── Stable claim contract ─────────────────────────────────────────────
CLAIM_KEYS: tuple[str, ...] = (
    "cluster.transaction_count",
    "cluster.filer_count",
    "cluster.shares_bought",
    "cluster.shares_sold",
    "cluster.dollar_bought",
    "cluster.dollar_sold",
    "cluster.net_shares",
    "cluster.net_dollars",
    "cluster.first_filing_date",
    "cluster.last_filing_date",
)

_DESCRIPTIONS: dict[str, str] = {
    "cluster.transaction_count": "Total Form 4 transactions in window",
    "cluster.filer_count": "Distinct insiders filing in window",
    "cluster.shares_bought": "Total shares bought (P transactions)",
    "cluster.shares_sold": "Total shares sold (S transactions)",
    "cluster.dollar_bought": "Total dollar value bought (P transactions)",
    "cluster.dollar_sold": "Total dollar value sold (S transactions)",
    "cluster.net_shares": "Net insider shares: bought minus sold",
    "cluster.net_dollars": "Net insider dollars: bought minus sold",
    "cluster.first_filing_date": "Earliest Form 4 filing date in window",
    "cluster.last_filing_date": "Most recent Form 4 filing date in window",
}

# Codes that count as real conviction signals. Everything else is
# accounting / compensation noise.
_BUY_CODE = "P"
_SELL_CODE = "S"


# ── Parsed transaction record (internal) ──────────────────────────────


@dataclass(frozen=True)
class _Form4Transaction:
    """One row from a Form 4 ``nonDerivativeTable``."""

    owner_cik: str
    owner_name: str
    date: str  # ISO YYYY-MM-DD
    code: str  # Form 4 transactionCode
    shares: float
    price: float


# ── XML parser ────────────────────────────────────────────────────────


def _text_or(elem: ET.Element | None, default: str = "") -> str:
    """``elem.text`` if present and not None, else default."""
    if elem is None or elem.text is None:
        return default
    return elem.text.strip()


def _value_under(parent: ET.Element | None, child_tag: str) -> str:
    """Form 4 wraps most fields in ``<child><value>X</value></child>`` — unwrap."""
    if parent is None:
        return ""
    child = parent.find(child_tag)
    if child is None:
        return ""
    value_elem = child.find("value")
    if value_elem is None:
        # Some fields are bare text under the child rather than nested in <value>.
        return _text_or(child)
    return _text_or(value_elem)


def _parse_form_4_xml(xml_text: str) -> list[_Form4Transaction]:
    """Pure parser: Form 4 XML → list of transactions. Raises on malformed XML."""
    root = ET.fromstring(xml_text)

    # Owner identification — at most one reportingOwner block matters for
    # the cluster summary (joint filings are rare; first owner wins).
    owner = root.find("reportingOwner")
    owner_id = owner.find("reportingOwnerId") if owner is not None else None
    owner_cik = _text_or(owner_id.find("rptOwnerCik")) if owner_id is not None else ""
    owner_name = (
        _text_or(owner_id.find("rptOwnerName")) if owner_id is not None else ""
    )

    out: list[_Form4Transaction] = []
    table = root.find("nonDerivativeTable")
    if table is None:
        return out

    for txn in table.findall("nonDerivativeTransaction"):
        date_str = _value_under(txn, "transactionDate")
        coding = txn.find("transactionCoding")
        code = _text_or(coding.find("transactionCode")) if coding is not None else ""
        amounts = txn.find("transactionAmounts")
        shares_str = _value_under(amounts, "transactionShares")
        price_str = _value_under(amounts, "transactionPricePerShare")

        try:
            shares = float(shares_str) if shares_str else 0.0
        except ValueError:
            shares = 0.0
        try:
            price = float(price_str) if price_str else 0.0
        except ValueError:
            price = 0.0

        out.append(
            _Form4Transaction(
                owner_cik=owner_cik,
                owner_name=owner_name,
                date=date_str,
                code=code,
                shares=shares,
                price=price,
            )
        )
    return out


# ── Aggregation ───────────────────────────────────────────────────────


def _aggregate(
    transactions: list[_Form4Transaction],
    filings: list[EdgarFiling],
) -> dict[str, ClaimValue | None]:
    """Roll a parsed-transaction list + the filings they came from into the cluster dict.

    All keys land in the output dict — None where no data exists, so
    the async entry point can stamp Claims uniformly without per-key
    presence checks.
    """
    if not filings:
        return {k: None for k in CLAIM_KEYS}

    shares_bought = sum(t.shares for t in transactions if t.code == _BUY_CODE)
    shares_sold = sum(t.shares for t in transactions if t.code == _SELL_CODE)
    dollar_bought = sum(
        t.shares * t.price for t in transactions if t.code == _BUY_CODE
    )
    dollar_sold = sum(
        t.shares * t.price for t in transactions if t.code == _SELL_CODE
    )

    # Distinct filers — match on CIK first (stable id), fall back to name.
    filers: set[str] = set()
    for t in transactions:
        key = t.owner_cik or t.owner_name
        if key:
            filers.add(key)

    filed_dates = sorted(f.filed_at.date() for f in filings)
    first = filed_dates[0].isoformat() if filed_dates else None
    last = filed_dates[-1].isoformat() if filed_dates else None

    return {
        "cluster.transaction_count": len(transactions),
        "cluster.filer_count": len(filers) if filers else None,
        "cluster.shares_bought": shares_bought,
        "cluster.shares_sold": shares_sold,
        "cluster.dollar_bought": dollar_bought,
        "cluster.dollar_sold": dollar_sold,
        "cluster.net_shares": shares_bought - shares_sold,
        "cluster.net_dollars": dollar_bought - dollar_sold,
        "cluster.first_filing_date": first,
        "cluster.last_filing_date": last,
    }


def _parse_filings(
    filings: Iterable[EdgarFiling],
) -> tuple[list[_Form4Transaction], int]:
    """Parse every filing's text; return (all_transactions, skipped_count).

    A filing without ``primary_doc_text`` is skipped (counted), as is
    one whose text fails to parse. Both failure modes are logged via
    the caller's observability record, not raised — we want the rest
    of the cluster.
    """
    all_txns: list[_Form4Transaction] = []
    skipped = 0
    for f in filings:
        if not f.primary_doc_text:
            skipped += 1
            continue
        try:
            all_txns.extend(_parse_form_4_xml(f.primary_doc_text))
        except Exception:  # noqa: BLE001 — one bad filing shouldn't kill the rest
            skipped += 1
    return all_txns, skipped


# ── Async entry point ─────────────────────────────────────────────────


async def parse_form_4_cluster(
    symbol: str,
    *,
    recent_n: int = 50,
    edgar_provider: str = "sec",
) -> dict[str, Claim]:
    """
    Pull the most recent ``recent_n`` Form 4 filings for ``symbol`` and
    return a cluster summary as ``dict[str, Claim]``.

    Stable shape: every key in ``CLAIM_KEYS`` is present, with
    ``Claim.value=None`` when no filings (or no parsable filings) were
    in the window. ``edgar_provider`` is forwarded to ``fetch_edgar``;
    failures inside ``fetch_edgar`` (CIK lookup, rate limit, network)
    propagate.
    """
    target = symbol.upper()
    service_id = f"{edgar_provider}.form_4"

    with log_external_call(
        service_id,
        {"symbol": target, "recent_n": recent_n, "edgar_provider": edgar_provider},
    ) as call:
        filings = await fetch_edgar(
            target,
            form_type="4",
            recent_n=recent_n,
            include_text=True,
            provider=edgar_provider,
        )
        transactions, skipped = _parse_filings(filings)
        agg = _aggregate(transactions, filings)
        call.record_output(
            {
                "filing_count": len(filings),
                "parsed_count": len(filings) - skipped,
                "skipped_count": skipped,
                "transaction_count": len(transactions),
            }
        )

    fetched_at = datetime.now(UTC)
    detail = _build_detail(filings, agg)

    out: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        out[key] = Claim(
            description=_DESCRIPTIONS[key],
            value=agg.get(key),
            source=Source(tool=service_id, fetched_at=fetched_at, detail=detail),
        )
    return out


def _build_detail(
    filings: list[EdgarFiling], agg: dict[str, ClaimValue | None]
) -> str:
    """Source.detail string the agent can quote in the report citation."""
    if not filings:
        return "computed: no Form 4 filings found in window"
    first = agg.get("cluster.first_filing_date")
    last = agg.get("cluster.last_filing_date")
    return (
        f"computed: aggregate of {len(filings)} Form 4 filings "
        f"filed {first} to {last}"
    )


# Re-exported for tests and external callers that want a thin handle on
# the pure parser without going through the async + observability path.
__all__ = ["CLAIM_KEYS", "parse_form_4_cluster", "_parse_form_4_xml"]
