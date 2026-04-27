"""
13F-HR institutional holdings parser. Closes the parse_filing trio.

13F-HR is filed quarterly by institutions (Berkshire, BlackRock,
Renaissance, …) about their portfolio holdings — the *inverted filer
pattern* relative to 10-K / Form 4. To find "13F filings that hold
AAPL", we iterate a curated list of notable institutions, fetch each
one's most recent 13F via fetch_edgar (using the cik= bypass — they
don't have tickers), parse each filing's <infoTable> rows, filter by
the target's CUSIP, and aggregate.

## Why curated institutions

The set of institutions whose 13Fs *matter for research* is small —
~25 firms that get press coverage when their positions move (Buffett,
BlackRock, Renaissance, Bridgewater, Pershing Square, …). Listing
them as a constant gives:

- **Determinism** — the agent's answer doesn't drift based on what
  SEC's full-text search ranks "relevant" today.
- **Free** — no third-party 13F aggregator (most are paywalled).
- **Cheap** — ~25 fetch_edgar calls per request, all cached.
- **Good signal-to-noise** — the included firms are the ones whose
  moves are interesting.

Trade-off: misses uncurated institutions. Add new firms to
``NOTABLE_INSTITUTIONS`` as research demand surfaces them.

## Why CUSIP-based filter

13F filings reference holdings by 9-character CUSIP, not ticker. The
``app.services.cusips`` map covers our SECTOR_PEERS set plus extras;
tickers outside that map cause this tool to short-circuit gracefully
(zero fetch_edgar calls, all-None claims, observability records
``reason: cusip_unknown``).

## Why aggregate-only

Per-institution Claims (e.g. ``BERKSHIRE.shares``) would scale with
institution count, balloon LLM context, and not change the agent's
answer for the typical research question. The 8 aggregate claims
this tool returns ("how many notable institutions hold it, what's the
total position, who's the biggest holder") are what the synth call
needs to write 'institutional flows' prose.

## Why exceptions propagate

Unlike news_ingestion's per-provider isolation, fetch_edgar errors
inside the institution loop propagate. The institution list is small;
a real EDGAR outage affects all of them, not one. Silent partial
results would hide the outage.

XML parse failures, missing primary_doc_text, and "no recent 13F"
*are* isolated — those are per-filing data quality issues, not
fetch-layer outages. They get recorded in the observability output's
``skipped_count``.

## Excluded for v1

- **Position changes vs prior 13F.** "Berkshire added 5M shares this
  quarter" requires fetching the institution's prior-period 13F and
  diffing. Defer until eval cases require it.
- **Non-curated institutions.** Add to ``NOTABLE_INSTITUTIONS`` as
  needed — one-line constant edit.
- **Schedule 13D/13G.** Those are activist-intent filings (≥5%
  positions) — different filing type, separate tool when needed.
- **Per-institution Claims.** Aggregate-only for v1.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.observability import log_external_call
from app.schemas.edgar import EdgarFiling
from app.schemas.research import Claim, ClaimValue, Source
from app.services.cusips import lookup_cusip
from app.services.edgar import fetch_edgar

# ── Stable claim contract ─────────────────────────────────────────────
CLAIM_KEYS: tuple[str, ...] = (
    "institutions.holding_count",
    "institutions.total_shares_held",
    "institutions.total_market_value",
    "institutions.holders_list",
    "institutions.top_holder_name",
    "institutions.top_holder_shares",
    "institutions.first_period",
    "institutions.last_period",
)

_DESCRIPTIONS: dict[str, str] = {
    "institutions.holding_count": "Number of curated notable institutions holding the symbol",
    "institutions.total_shares_held": "Total shares held across reporting institutions",
    "institutions.total_market_value": "Total reported market value ($1000s, per 13F convention)",
    "institutions.holders_list": "Comma-separated names of institutions holding the symbol",
    "institutions.top_holder_name": "Largest position by shares (tie broken alphabetically)",
    "institutions.top_holder_shares": "Shares held by the top holder",
    "institutions.first_period": "Earliest period_of_report among parsed 13F filings (ISO date)",
    "institutions.last_period": "Most recent period_of_report among parsed 13F filings (ISO date)",
}


# ── Curated institution list ──────────────────────────────────────────
# Tuples of (CIK, label). CIKs are 10-digit zero-padded. Labels appear
# in holders_list and top_holder_name claims, so they should be short
# and recognizable. Add new firms here when research demand surfaces
# them — the addition propagates through the rest of the tool.
NOTABLE_INSTITUTIONS: list[tuple[str, str]] = [
    ("0001067983", "BERKSHIRE_HATHAWAY"),
    ("0001364742", "BLACKROCK"),
    ("0000102909", "VANGUARD"),
    ("0000093751", "STATE_STREET"),
    ("0000315066", "FIDELITY_FMR"),
    ("0001037389", "RENAISSANCE_TECHNOLOGIES"),
    ("0001423053", "CITADEL_ADVISORS"),
    ("0001179392", "TWO_SIGMA"),
    ("0001350694", "BRIDGEWATER"),
    ("0001697748", "ARK_INVEST"),
    ("0001167483", "TIGER_GLOBAL"),
    ("0001336528", "PERSHING_SQUARE"),
    ("0001079114", "GREENLIGHT_CAPITAL"),
    ("0001035674", "PAULSON_AND_CO"),
    ("0001061165", "LONE_PINE_CAPITAL"),
    ("0001135730", "COATUE_MANAGEMENT"),
    ("0001418814", "VALUEACT_CAPITAL"),
    ("0001040273", "THIRD_POINT"),
    ("0001345471", "TRIAN_FUND_MANAGEMENT"),
]


# ── Pure XML parser ───────────────────────────────────────────────────


@dataclass(frozen=True)
class _HoldingRow:
    """One <infoTable> row that matched the target CUSIP."""

    name: str  # nameOfIssuer
    cusip: str  # 9-char CUSIP
    shares: int  # sshPrnamt (share count)
    value: int  # value ($1000s, per 13F convention)


def _strip_namespace(root: ET.Element) -> None:
    """
    Remove XML namespace prefixes from ``root`` and all descendants.

    13F-HR documents carry a versioned namespace
    (``http://www.sec.gov/edgar/document/thirteenf/informationtable``)
    that ElementTree decorates onto every tag — turning ``infoTable``
    into ``{NS}infoTable``. Filers occasionally omit the xmlns or use
    a different version. Stripping upfront lets the rest of the
    parser use bare tag names regardless of which way the filer went.
    """
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _findtext(elem: ET.Element, tag: str) -> str:
    """Convenience wrapper: child's text or empty string."""
    found = elem.find(tag)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def _parse_13f_xml(xml_text: str, *, target_cusip: str) -> list[_HoldingRow]:
    """
    Parse a 13F-HR informationTable XML body, return rows whose CUSIP
    matches ``target_cusip``.

    Raises on malformed XML — the async layer catches and skips that
    filing rather than killing the whole call.
    """
    root = ET.fromstring(xml_text)
    _strip_namespace(root)
    target_norm = target_cusip.upper()

    out: list[_HoldingRow] = []
    for info in root.findall("infoTable"):
        cusip = _findtext(info, "cusip").upper()
        if cusip != target_norm:
            continue

        name = _findtext(info, "nameOfIssuer")

        # Value is reported in $1000s per SEC 13F convention.
        value_str = _findtext(info, "value")
        try:
            value = int(float(value_str)) if value_str else 0
        except ValueError:
            value = 0

        # Shares live nested under shrsOrPrnAmt > sshPrnamt.
        shrs = info.find("shrsOrPrnAmt")
        shares_str = _findtext(shrs, "sshPrnamt") if shrs is not None else ""
        try:
            shares = int(float(shares_str)) if shares_str else 0
        except ValueError:
            shares = 0

        out.append(_HoldingRow(name=name, cusip=cusip, shares=shares, value=value))
    return out


# ── Aggregation ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class _InstitutionPosition:
    """One institution's aggregate position in the target symbol from one 13F."""

    institution_label: str
    period_of_report: str  # ISO date
    shares: int
    value: int


def _aggregate(positions: list[_InstitutionPosition]) -> dict[str, ClaimValue | None]:
    """Roll per-institution positions into the final claims dict."""
    if not positions:
        return {k: None for k in CLAIM_KEYS}

    total_shares = sum(p.shares for p in positions)
    total_value = sum(p.value for p in positions)

    # Holders sorted alphabetically for deterministic output.
    holder_names = sorted(p.institution_label for p in positions)

    # Top holder by shares; tie broken alphabetically (positions sort
    # primary key shares desc, secondary key name asc).
    top = sorted(positions, key=lambda p: (-p.shares, p.institution_label))[0]

    periods = sorted(p.period_of_report for p in positions if p.period_of_report)

    return {
        "institutions.holding_count": len(positions),
        "institutions.total_shares_held": total_shares,
        "institutions.total_market_value": total_value,
        "institutions.holders_list": ", ".join(holder_names),
        "institutions.top_holder_name": top.institution_label,
        "institutions.top_holder_shares": top.shares,
        "institutions.first_period": periods[0] if periods else None,
        "institutions.last_period": periods[-1] if periods else None,
    }


# ── Async entry point ─────────────────────────────────────────────────


async def parse_13f_holdings(
    symbol: str,
    *,
    edgar_provider: str = "sec",
) -> dict[str, Claim]:
    """
    Aggregate institutional holdings of ``symbol`` across the curated list.

    Returns a stable ``dict[str, Claim]`` with 8 keys. When the symbol
    isn't in our CUSIP map, returns all-None claims and skips the
    institution loop entirely (zero fetch_edgar calls).
    """
    target = symbol.upper()
    service_id = f"{edgar_provider}.holdings_13f"

    target_cusip = lookup_cusip(target)
    fetched_at = datetime.now(UTC)
    detail = "computed: aggregate of curated NOTABLE_INSTITUTIONS 13F-HR filings"

    if target_cusip is None:
        with log_external_call(
            service_id,
            {"symbol": target, "edgar_provider": edgar_provider},
        ) as call:
            call.record_output(
                {
                    "institutions_queried": 0,
                    "parsed_count": 0,
                    "skipped_count": 0,
                    "holders_found": 0,
                    "reason": "cusip_unknown",
                }
            )
        return _build_empty(service_id=service_id, fetched_at=fetched_at, detail=detail)

    with log_external_call(
        service_id,
        {"symbol": target, "edgar_provider": edgar_provider},
    ) as call:
        positions: list[_InstitutionPosition] = []
        parsed_count = 0
        skipped_count = 0

        for cik, label in NOTABLE_INSTITUTIONS:
            filings = await fetch_edgar(
                f"{label}_13F",
                form_type="13F-HR",
                recent_n=1,
                include_text=True,
                provider=edgar_provider,
                cik=cik,
            )
            if not filings:
                # Institution had no recent 13F — uncommon but possible
                # (e.g. firm wound down). Not an error; just skip.
                skipped_count += 1
                continue

            filing = filings[0]
            position = _extract_position(filing, label, target_cusip)
            if position is None:
                skipped_count += 1
                continue

            parsed_count += 1
            if position.shares > 0:
                positions.append(position)

        call.record_output(
            {
                "institutions_queried": len(NOTABLE_INSTITUTIONS),
                "parsed_count": parsed_count,
                "skipped_count": skipped_count,
                "holders_found": len(positions),
            }
        )

    agg = _aggregate(positions)
    return _build_claims(
        service_id=service_id,
        fetched_at=fetched_at,
        detail=detail,
        agg=agg,
    )


def _extract_position(
    filing: EdgarFiling,
    institution_label: str,
    target_cusip: str,
) -> _InstitutionPosition | None:
    """
    Extract one institution's position in the target from one 13F filing.

    Returns ``None`` (and the caller increments skipped_count) when:
    - the filing has no primary_doc_text
    - the XML doesn't parse
    - the institution doesn't hold the target (no matching CUSIP rows)

    When multiple <infoTable> rows match the same CUSIP for one
    institution (rare but allowed — e.g. multiple share classes), they
    sum into a single _InstitutionPosition.
    """
    if not filing.primary_doc_text:
        return None

    try:
        rows = _parse_13f_xml(
            filing.primary_doc_text, target_cusip=target_cusip
        )
    except Exception:  # noqa: BLE001 — one bad filing shouldn't kill the call
        return None

    if not rows:
        # No matching CUSIP — this institution doesn't hold the target.
        # That's a "parsed successfully, just no position" outcome, so
        # we return None but the caller treats it as parsed (parsed_count
        # increments, holders_found doesn't).
        return _InstitutionPosition(
            institution_label=institution_label,
            period_of_report=(
                filing.period_of_report.isoformat() if filing.period_of_report else ""
            ),
            shares=0,
            value=0,
        )

    total_shares = sum(r.shares for r in rows)
    total_value = sum(r.value for r in rows)
    return _InstitutionPosition(
        institution_label=institution_label,
        period_of_report=(
            filing.period_of_report.isoformat() if filing.period_of_report else ""
        ),
        shares=total_shares,
        value=total_value,
    )


def _build_claims(
    *,
    service_id: str,
    fetched_at: datetime,
    detail: str,
    agg: dict[str, ClaimValue | None],
) -> dict[str, Claim]:
    """Stamp Source onto every aggregate value to produce the final claim dict."""
    out: dict[str, Claim] = {}
    for key in CLAIM_KEYS:
        out[key] = Claim(
            description=_DESCRIPTIONS[key],
            value=agg.get(key),
            source=Source(tool=service_id, fetched_at=fetched_at, detail=detail),
        )
    return out


def _build_empty(
    *,
    service_id: str,
    fetched_at: datetime,
    detail: str,
) -> dict[str, Claim]:
    """All-None claim dict — used when CUSIP is unknown so we never fetch_edgar."""
    return _build_claims(
        service_id=service_id,
        fetched_at=fetched_at,
        detail=detail,
        agg={k: None for k in CLAIM_KEYS},
    )


# Re-exported for tests (monkey-patching at the module-import boundary).
__all__ = [
    "CLAIM_KEYS",
    "NOTABLE_INSTITUTIONS",
    "parse_13f_holdings",
    "_parse_13f_xml",
    "fetch_edgar",  # noqa: F822 — surfaced for tests' monkeypatch
]
