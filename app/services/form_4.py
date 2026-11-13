"""
Insider activity from Form 4 filings (2026-11).

Officers, directors and 10%+ holders must file a Form 4 within two
business days of trading the company's stock. The filing is structured
XML, so who traded, in which direction, how many shares and at what
price sit at known paths.

What a reader wants from it is whether the people running the company
are buying or selling, and how much that says. A naive sum of every
Form 4 in the company's SEC list says the wrong thing in three ways,
all found on real filings (tasks/dogfood-2026-11.md):

1. **The list holds Form 4s about other companies.** A company that owns
   10% or more of another files Form 4s as that owner, and they appear in
   its own list: Exxon's $277M "sale" was Exxon selling Imperial Oil
   shares. Only filings whose issuer is the company count.
2. **10%+ holders are not insiders in the sense that matters.**
   Volkswagen's $1B purchase of Rivian shares is a strategic investment,
   not an executive buying with their own money. Officers and directors
   are summed apart from other reporting owners.
3. **Most executive selling is pre-scheduled.** Since 2023 a Form 4 says
   whether the trade was made under a 10b5-1 trading plan, set up months
   ahead. The share of selling made under plans is reported, so a large
   but routine program reads as one.

Only transaction codes ``P`` (purchase) and ``S`` (sale) are trades.
Grants (``A``), option exercises (``M``), tax withholding (``F``) and
gifts (``G``) are counted as routine. Option and other derivative rows
are not read. A sale whose price is reported only in a footnote counts
as $0, which understates rather than invents.

**Window.** The last ``WINDOW_DAYS`` days, by filing date for which
filings are read and by transaction date for what is summed, capped at
the ``MAX_FILINGS`` most recent filings. The claims name the span
actually covered.

**Cost.** One request lists the filings; each filing in the window is
one more (about 40-70 for a large company), downloaded once and then
reused from the disk cache (``edgar.fetch_edgar``).

``fetch_edgar`` is imported at module load so tests replace it here.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from app.core.observability import log_external_call
from app.schemas.edgar import EdgarFiling
from app.schemas.research import Claim, ClaimUnit, ClaimValue, Source
from app.services.edgar import fetch_edgar

WINDOW_DAYS = 183
MAX_FILINGS = 100
MAX_PEOPLE = 5
TOOL = "sec.form_4"
_WINDOW = "last 6 months"

_BUY, _SELL = "P", "S"

# Fixed claims: every key present on every result (None when unknown).
CLAIM_KEYS: tuple[str, ...] = (
    "filing_count",
    "first_filing_date",
    "last_filing_date",
    "buy_dollars",
    "buyer_count",
    "sell_dollars",
    "seller_count",
    "net_dollars",
    "plan_sale_share",
    "routine_count",
    "holder_buy_dollars",
    "holder_sell_dollars",
)

DESCRIPTIONS: dict[str, str] = {
    "filing_count": f"Form 4 filings about the company, {_WINDOW}",
    "first_filing_date": "Earliest Form 4 filing in the window",
    "last_filing_date": "Most recent Form 4 filing",
    "buy_dollars": f"Purchases by officers and directors, {_WINDOW}",
    "buyer_count": f"Officers and directors who bought, {_WINDOW}",
    "sell_dollars": f"Sales by officers and directors, {_WINDOW}",
    "seller_count": f"Officers and directors who sold, {_WINDOW}",
    "net_dollars": f"Net officer and director buying (+) or selling (−), {_WINDOW}",
    "plan_sale_share": "Share of officer and director sales made under 10b5-1 trading plans",
    "routine_count": f"Grants, option exercises, tax withholdings and gifts, {_WINDOW} (not buys or sales)",
    "holder_buy_dollars": f"Purchases by 10% holders and other reporting owners, {_WINDOW}",
    "holder_sell_dollars": f"Sales by 10% holders and other reporting owners, {_WINDOW}",
}

UNITS: dict[str, ClaimUnit] = {
    "filing_count": "count",
    "first_filing_date": "date",
    "last_filing_date": "date",
    "buy_dollars": "usd",
    "buyer_count": "count",
    "sell_dollars": "usd",
    "seller_count": "count",
    "net_dollars": "usd",
    "plan_sale_share": "fraction",
    "routine_count": "count",
    "holder_buy_dollars": "usd",
    "holder_sell_dollars": "usd",
}

assert set(DESCRIPTIONS) == set(UNITS) == set(CLAIM_KEYS)


# ── Parsing ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Transaction:
    date: str  # ISO date as filed; may be empty
    code: str
    shares: float
    price: float

    @property
    def dollars(self) -> float:
        return self.shares * self.price


@dataclass(frozen=True)
class Form4:
    issuer_cik: str
    owner_cik: str
    owner_name: str
    role: str
    is_insider: bool
    under_plan: bool | None
    transactions: tuple[Transaction, ...]


def _flag(text: str | None) -> bool:
    return (text or "").strip().lower() in ("1", "true")


def _number(text: str | None) -> float:
    try:
        return float((text or "").strip() or 0)
    except ValueError:
        return 0.0


# An owner marked "other" whose description names one of these is an
# executive in all but the checkbox: Coca-Cola files its regional
# presidents as "other" ("President, Latin America OU").
_EXECUTIVE_WORDS = re.compile(
    r"\b(president|chief|officer|vp|vice president|director|head|ceo|cfo|coo|cto|"
    r"chair|chairman|treasurer|controller|secretary|general counsel)\b",
    re.IGNORECASE,
)


def _role(rel: ET.Element | None) -> tuple[str, bool]:
    """(role as shown, whether the owner is an officer or director)."""
    if rel is None:
        return "Other", False
    officer = _flag(rel.findtext("isOfficer"))
    director = _flag(rel.findtext("isDirector"))
    title = (rel.findtext("officerTitle") or "").strip()
    if officer and title:
        return title[:60], True
    if officer:
        return "Officer", True
    if director:
        return "Director", True
    if _flag(rel.findtext("isTenPercentOwner")):
        return "10% owner", False
    other = (rel.findtext("otherText") or "").strip()
    if _flag(rel.findtext("isOther")) and other:
        return other[:60], bool(_EXECUTIVE_WORDS.search(other)) and "10%" not in other
    return "Other", False


def parse_form_4(xml_text: str) -> Form4:
    """One Form 4's issuer, owner and non-derivative transactions.
    Raises on malformed XML.

    A joint filing (a director and their family trust, a fund and its
    general partner) reports each trade once; it is attributed to the
    first owner who is an officer or director, else to the first owner.
    """
    root = ET.fromstring(xml_text)
    owners = []
    for owner in root.findall("reportingOwner"):
        role, insider = _role(owner.find("reportingOwnerRelationship"))
        owners.append((
            (owner.findtext("reportingOwnerId/rptOwnerCik") or "").strip(),
            (owner.findtext("reportingOwnerId/rptOwnerName") or "").strip(),
            role,
            insider,
        ))
    chosen = next((o for o in owners if o[3]), owners[0] if owners else ("", "", "Other", False))

    plan_text = root.findtext("aff10b5One")
    under_plan = None if plan_text is None or not plan_text.strip() else _flag(plan_text)

    transactions = tuple(
        Transaction(
            date=(txn.findtext("transactionDate/value") or "").strip(),
            code=(txn.findtext("transactionCoding/transactionCode") or "").strip(),
            shares=_number(txn.findtext("transactionAmounts/transactionShares/value")),
            price=_number(txn.findtext("transactionAmounts/transactionPricePerShare/value")),
        )
        for txn in root.findall("nonDerivativeTable/nonDerivativeTransaction")
    )
    return Form4(
        issuer_cik=(root.findtext("issuer/issuerCik") or "").strip(),
        owner_cik=chosen[0],
        owner_name=chosen[1],
        role=chosen[2],
        is_insider=chosen[3],
        under_plan=under_plan,
        transactions=transactions,
    )


# ── Summary ──────────────────────────────────────────────────────────


@dataclass
class Person:
    name: str
    role: str
    is_insider: bool
    bought: float = 0.0
    sold: float = 0.0
    trades: int = 0

    @property
    def net(self) -> float:
        return self.bought - self.sold


@dataclass
class Summary:
    filing_count: int = 0
    skipped_count: int = 0
    other_issuer_count: int = 0
    first_filing_date: str | None = None
    last_filing_date: str | None = None
    buy_dollars: float = 0.0
    sell_dollars: float = 0.0
    holder_buy_dollars: float = 0.0
    holder_sell_dollars: float = 0.0
    routine_count: int = 0
    plan_sale_share: float | None = None
    buyers: set[str] = field(default_factory=set)
    sellers: set[str] = field(default_factory=set)
    people: list[Person] = field(default_factory=list)

    @property
    def buyer_count(self) -> int:
        return len(self.buyers)

    @property
    def seller_count(self) -> int:
        return len(self.sellers)

    @property
    def net_dollars(self) -> float:
        return self.buy_dollars - self.sell_dollars


def _same_cik(a: str, b: str) -> bool:
    try:
        return int(a) == int(b)
    except ValueError:
        return False


def summarize(filings: list[EdgarFiling], *, today: date) -> Summary:
    """Sum the trades in ``filings`` (with text) dated within the window.

    A filing is skipped when it has no text or doesn't parse, and left out
    when its issuer isn't the registrant whose list it came from.
    """
    cutoff = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    s = Summary()
    people: dict[str, Person] = {}
    plan_sold = known_plan_sold = 0.0
    dates: list[str] = []

    for filing in filings:
        if filing.filed_at.date().isoformat() < cutoff:
            continue  # filed before the window
        if not filing.primary_doc_text:
            s.skipped_count += 1
            continue
        try:
            doc = parse_form_4(filing.primary_doc_text)
        except ET.ParseError:
            s.skipped_count += 1
            continue
        if not _same_cik(doc.issuer_cik, filing.cik):
            s.other_issuer_count += 1
            continue
        s.filing_count += 1
        dates.append(filing.filed_at.date().isoformat())
        key = doc.owner_cik or doc.owner_name
        for txn in doc.transactions:
            when = txn.date or filing.filed_at.date().isoformat()
            if when < cutoff:
                continue
            if txn.code not in (_BUY, _SELL):
                s.routine_count += 1
                continue
            person = people.setdefault(key, Person(name=doc.owner_name, role=doc.role, is_insider=doc.is_insider))
            person.trades += 1
            if txn.code == _BUY:
                person.bought += txn.dollars
                if doc.is_insider:
                    s.buy_dollars += txn.dollars
                    s.buyers.add(key)
                else:
                    s.holder_buy_dollars += txn.dollars
            else:
                person.sold += txn.dollars
                if doc.is_insider:
                    s.sell_dollars += txn.dollars
                    s.sellers.add(key)
                    if doc.under_plan is not None:
                        known_plan_sold += txn.dollars
                        if doc.under_plan:
                            plan_sold += txn.dollars
                else:
                    s.holder_sell_dollars += txn.dollars

    if dates:
        s.first_filing_date, s.last_filing_date = min(dates), max(dates)
    if known_plan_sold > 0:
        s.plan_sale_share = plan_sold / known_plan_sold
    s.people = sorted(people.values(), key=lambda p: p.bought + p.sold, reverse=True)[:MAX_PEOPLE]
    return s


# ── Claims ───────────────────────────────────────────────────────────


def _usd(v: float) -> str:
    return f"${v:,.0f}"


def _values(s: Summary | None, latest_listed: str | None) -> dict[str, ClaimValue]:
    if s is None:
        # Filings exist but none in the window: say so, and when the last was.
        return {"filing_count": 0, "last_filing_date": latest_listed}
    return {
        "filing_count": s.filing_count,
        "first_filing_date": s.first_filing_date,
        "last_filing_date": s.last_filing_date or latest_listed,
        "buy_dollars": s.buy_dollars,
        "buyer_count": s.buyer_count,
        "sell_dollars": s.sell_dollars,
        "seller_count": s.seller_count,
        "net_dollars": s.net_dollars,
        "plan_sale_share": s.plan_sale_share,
        "routine_count": s.routine_count,
        "holder_buy_dollars": s.holder_buy_dollars,
        "holder_sell_dollars": s.holder_sell_dollars,
    }


def build_claims(
    s: Summary | None,
    *,
    latest_listed: str | None,
    fetched_at: datetime | None = None,
) -> dict[str, Claim]:
    """The fixed claims (all None when the company files no Form 4s), then
    one ``person.N`` claim per top trader."""
    at = fetched_at or datetime.now(UTC)
    if latest_listed is None:
        detail = "no Form 4 filings found"
        values: dict[str, ClaimValue] = {}
    elif s is None or s.filing_count == 0:
        detail = f"no Form 4 filings about the company in the {_WINDOW}; most recent filed {latest_listed}"
        values = _values(None, latest_listed)
    else:
        detail = (
            f"{s.filing_count} Form 4 filings filed {s.first_filing_date} to {s.last_filing_date}; "
            "officers and directors apart from 10% holders; codes P and S only"
        )
        values = _values(s, latest_listed)

    def source(text: str = detail) -> Source:
        return Source(tool=TOOL, fetched_at=at, detail=text[:256])

    claims = {
        key: Claim(description=DESCRIPTIONS[key], value=values.get(key), unit=UNITS[key], source=source())
        for key in CLAIM_KEYS
    }
    for i, person in enumerate(s.people if s else [], start=1):
        claims[f"person.{i}"] = Claim(
            description=f"{person.name} ({person.role}): net bought (+) or sold (−), {_WINDOW}"[:200],
            value=person.net,
            unit="usd",
            source=source(f"bought {_usd(person.bought)}, sold {_usd(person.sold)} across {person.trades} trades"),
        )
    return claims


# ── Tool ─────────────────────────────────────────────────────────────


async def fetch_insider_activity(
    symbol: str,
    *,
    provider: str = "sec",
    today: date | None = None,
) -> dict[str, Claim]:
    """Insider buying and selling over the last six months. See the
    module docstring."""
    target = symbol.upper()
    day = today or datetime.now(UTC).date()
    cutoff = day - timedelta(days=WINDOW_DAYS)

    with log_external_call(TOOL, {"symbol": target, "provider": provider}) as call:
        listed = await fetch_edgar(
            target, form_type="4", recent_n=MAX_FILINGS, include_text=False, provider=provider
        )
        in_window = sum(1 for f in listed if f.filed_at.date() >= cutoff)
        filings = (
            await fetch_edgar(target, form_type="4", recent_n=in_window, include_text=True, provider=provider)
            if in_window
            else []
        )
        summary = summarize(filings, today=day) if filings else None
        call.record_output({
            "listed": len(listed),
            "in_window": in_window,
            "counted": summary.filing_count if summary else 0,
            "other_issuer": summary.other_issuer_count if summary else 0,
            "skipped": summary.skipped_count if summary else 0,
        })

    latest = max((f.filed_at.date() for f in listed), default=None)
    return build_claims(summary, latest_listed=latest.isoformat() if latest else None)
