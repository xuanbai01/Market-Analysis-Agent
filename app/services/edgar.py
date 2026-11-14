"""
SEC EDGAR filing fetcher.

Given a ticker, a form type, and a count, returns the most recent N
filings as ``EdgarFiling`` records — metadata only by default, with
optional primary-document text. Filings are inputs to ``parse_filing``
(which produces the ``Claim`` records that land in the report); this
tool's job is purely to fetch + cache.

## Why disk cache rather than DB

Filings are immutable. Once an accession number is assigned, the
underlying document never changes — amendments get a new accession.
That means we need no invalidation, no expiry, no last-modified probe:
write on cache miss, read on cache hit, forever. A filesystem cache is
the simplest implementation that respects that. A ``filings`` table in
Postgres only earns its keep when ``search_history`` (pgvector RAG over
filings) lands; until then a directory of JSON files is plenty.

The cache layout is:

    {EDGAR_CACHE_DIR}/{cik}/{accession}/metadata.json    — EdgarFiling JSON, with its text
    {EDGAR_CACHE_DIR}/{symbol}/{form_type}.json           — the latest filings

The ``{symbol}/{form_type}.json`` index is what lets us answer "give me
the most recent 3 10-Ks for AAPL" without re-hitting EDGAR's submissions
endpoint. It is the provider's last answer: ``recent_n``, how many
filings it was asked for, and ``filings``, the newest it found, newest
first. On a cache miss we write each filing's metadata and replace the
index.

## Why an explicit form_type allowlist

EDGAR has dozens of form types; we only need a handful (10-K, 10-Q,
8-K, 4 in v1). Restricting at the API boundary surfaces typos and
prevents the agent from trying to fetch shapes the parsers don't
understand. 13F is *deliberately* not here — those are filed by
institutions, not by the company being researched, and need a
different fetcher (search by filer mentioning ticker, not by ticker's
own CIK).

## Provider registry

Same shape as fundamentals/peers/news. ``_fetch_edgar_sec`` is the
production provider; tests register a fake via
``monkeypatch.setitem(PROVIDERS, "fake", ...)``. The SEC HTTP path is
not unit-tested here (same convention as yfinance) — it's exercised
post-merge with a smoke test, where flaky networks and the SEC's
fair-access policy can do their worst without breaking the suite.

## SEC fair-access compliance

SEC requires a ``User-Agent`` identifying the client. ``EDGAR_USER_AGENT``
in settings is the source of truth; the provider attaches it to every
HTTP call. SEC's rate limit is ≤10 req/sec per client. Several tools
call SEC from parallel threads (the 10-K extractors, the annual history,
insider activity), so ``_sec_get`` spaces requests across all of them
with one lock: at most 8 a second for the whole process.

## Cache freshness

A filing's text never changes, so it is downloaded once and reused by
accession. The per-(symbol, form) index of which filings exist does
change: it is trusted for ``INDEX_TTL_SECONDS`` and then the provider
is asked again (until 2026-11 it was trusted forever, so a machine that
had cached two 10-Ks never saw a third). While fresh it answers any
request for up to ``recent_n`` filings, including one where SEC had
fewer. Until 2026-11-14 it was a list appended in the order filings were
first seen, and its first entries were served: a new 10-K went to the
end, and the two before it were served as the latest.
Both rules are documented at
https://www.sec.gov/os/accessing-edgar-data.

## Older pages

``filings.recent`` in SEC's submissions JSON holds a year of filings at
least (or 1,000); older ones are in pages listed under ``filings.files``.
For most companies a year holds two 10-Ks. A bank that issues notes
every day does not: JPM's ``recent`` is one year of 26,000 filings, so
until 2026-11-14 its 10-K before last was never found and its report had
no risk changes. The provider reads older pages until it has enough,
back to ``OLDER_PAGES_YEARS`` before the latest filing.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.observability import log_external_call
from app.core.settings import settings
from app.schemas.edgar import EdgarFiling
from app.services import sec_registrants

# ── Form-type allowlist ───────────────────────────────────────────────
# Forms the parsers understand. 13F-HR is filed by *institutions* about
# their portfolio holdings (not by the company being researched), so
# callers fetching 13Fs must pass ``cik=`` directly — the ticker→CIK
# lookup wouldn't find an institution. See holdings_13f for the caller.
SUPPORTED_FORM_TYPES: frozenset[str] = frozenset(
    {
        "10-K",     # annual report
        "10-Q",     # quarterly report
        "8-K",      # current events / earnings release
        "4",        # insider transactions (Form 4)
        "13F-HR",   # institutional holdings (cik= required, not symbol)
    }
)


# Provider signature: (symbol, form_type, recent_n, include_text, cik) ->
# filings. ``cik`` is optional: when non-None, the provider should skip
# its ticker→CIK lookup and use the provided CIK directly. Sync — the
# production provider uses httpx (which is sync by default when called
# as ``httpx.get``); the async entry point hands it to ``asyncio.to_thread``
# so the event loop stays free.
EdgarProvider = Callable[[str, str, int, bool, str | None], list[EdgarFiling]]


# ── Cache helpers ─────────────────────────────────────────────────────


# How long the list of which filings exist is trusted before SEC is
# asked again. Filing texts themselves are cached forever.
INDEX_TTL_SECONDS = 12 * 3600


def _cache_root() -> Path:
    """Resolve EDGAR_CACHE_DIR at call time so settings overrides take effect."""
    return Path(settings.EDGAR_CACHE_DIR)


def _cache_key_dir(root: Path, cik: str, accession: str) -> Path:
    """Per-filing directory: ``{root}/{cik}/{accession}/``."""
    return root / cik / accession


def _index_path(root: Path, symbol: str, form_type: str) -> Path:
    """Per-(symbol, form_type) accession index file."""
    return root / symbol / f"{form_type}.json"


def _atomic_write(path: Path, payload: str) -> None:
    """Write text atomically: temp file in same dir, then rename.

    Same-directory-then-rename guarantees the rename is atomic on POSIX
    and Windows — avoids partial files if the process is killed mid-
    write. We don't fsync; cache durability is best-effort, the worst
    case is a re-fetch on next call.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _read_cached_filing(root: Path, cik: str, accession: str) -> EdgarFiling | None:
    """Best-effort load of a cached filing; None on any read/decode failure."""
    meta_path = _cache_key_dir(root, cik, accession) / "metadata.json"
    if not meta_path.exists():
        return None
    try:
        return EdgarFiling.model_validate_json(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt cache → treat as miss
        return None


def _read_fresh_index(root: Path, symbol: str, form_type: str) -> dict[str, Any] | None:
    """The (symbol, form_type) index if written within ``INDEX_TTL_SECONDS``.

    None when it is missing, older, unreadable, or in the format from
    before 2026-11-14: a plain list in the order filings were first seen,
    which on a warm cache led with the oldest (AAPL's read FY2025, FY2024,
    FY2026, so its two "latest" 10-Ks were a year behind).
    """
    path = _index_path(root, symbol, form_type)
    try:
        if time.time() - path.stat().st_mtime > INDEX_TTL_SECONDS:
            return None
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (
        isinstance(index, dict)
        and isinstance(index.get("recent_n"), int)
        and isinstance(index.get("filings"), list)
    ):
        return None
    return index


def _write_index(
    root: Path, symbol: str, form_type: str, recent_n: int, newest: list[EdgarFiling]
) -> None:
    """Record the provider's answer to a request for ``recent_n`` filings:
    ``newest``, newest first, and fewer than ``recent_n`` when that is all
    there is. A fresh index that answers more is kept: Form 4 lists up to a
    hundred, then asks for the texts of the few in its window, and that
    second answer must not send the next listing back to SEC."""
    current = _read_fresh_index(root, symbol, form_type)
    if current is not None and current["recent_n"] > recent_n:
        return
    entries = [{"cik": f.cik, "accession": f.accession} for f in newest]
    _atomic_write(
        _index_path(root, symbol, form_type),
        json.dumps({"recent_n": recent_n, "filings": entries}),
    )


def _write_filing_to_cache(root: Path, filing: EdgarFiling) -> None:
    """Cache one filing's metadata (and text, when it has it)."""
    cache_dir = _cache_key_dir(root, filing.cik, filing.accession)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(cache_dir / "metadata.json", filing.model_dump_json())


# ── Production provider — SEC HTTP ────────────────────────────────────
# Not unit-tested in the suite; exercised post-merge via a smoke test.
# Kept defensive (any HTTP / parsing failure raises) so the async entry
# point's log_external_call records the outcome accurately.


# How far back older pages of a submissions JSON are read, from the
# registrant's latest filing. The 10-K before last is under two years
# old; without a limit, a form asked for in bulk (Form 4's hundred) or
# rarely filed would page through all of a bank's history (JPM: 72 pages
# of 2,000 filings).
OLDER_PAGES_YEARS = 3

# Minimum gap between any two SEC requests from this process, whatever
# thread they come from: 8 a second, under SEC's 10.
_SEC_MIN_INTERVAL_SECONDS = 0.125
_sec_lock = threading.Lock()
_sec_last_request = 0.0

# SEC's submissions JSON returns ``primaryDocument`` as the
# stylesheet-rendered HTML version for filings whose underlying
# document is XML (Forms 3/4/5 use ``xslF345X06/``, ``xslF345X05/``,
# etc.; Schedule 13D/G uses ``xslSCHEDULE_13D_X01/``). The bare path on
# the same accession serves the raw XML. Programmatic parsers want the
# raw XML, so we strip the prefix before constructing the URL.
_XSL_PREFIX_PAT = re.compile(r"^xsl[\w]+/")


def _strip_xsl_prefix(primary_doc: str) -> str:
    """Strip a leading ``xsl*/`` segment from a SEC primary-document path.

    No-op when the path doesn't start with an XSL segment, so 10-K HTML
    paths and other non-rendered docs pass through unchanged.
    """
    return _XSL_PREFIX_PAT.sub("", primary_doc)


def _sec_get(url: str) -> httpx.Response:
    """One polite GET against SEC: required User-Agent, and spaced from
    every other SEC request in the process (see the module docstring)."""
    global _sec_last_request
    with _sec_lock:
        wait = _sec_last_request + _SEC_MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _sec_last_request = time.monotonic()
    headers = {
        "User-Agent": settings.EDGAR_USER_AGENT,
        "Accept": "application/json,text/html,*/*",
    }
    resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    return resp


def _resolve_cik(symbol: str) -> str:
    """Look up CIK for a ticker via SEC's company_tickers.json mapping."""
    resp = _sec_get("https://www.sec.gov/files/company_tickers.json")
    data = resp.json()
    # company_tickers.json is shaped {"0": {"cik_str": int, "ticker": str, ...}, ...}
    for row in data.values():
        if row.get("ticker", "").upper() == symbol:
            return f"{int(row['cik_str']):010d}"
    raise ValueError(f"Ticker {symbol!r} not found in SEC ticker map")


def _fetch_edgar_sec(
    symbol: str,
    form_type: str,
    recent_n: int,
    include_text: bool,
    cik: str | None = None,
) -> list[EdgarFiling]:
    """Production provider: ticker → CIK → submissions JSON → recent N filings.

    When ``cik`` is provided, the ticker→CIK lookup is skipped and the
    provided CIK is used directly. holdings_13f relies on this because
    institution filers don't have tickers in ``company_tickers.json``.
    """
    if cik is None:
        cik = _resolve_cik(symbol)
    # A company that reorganized under a new registrant keeps its older
    # filings under the one before it (sec_registrants). A filing made
    # jointly appears under both; the current registrant's copy is kept.
    by_accession: dict[str, EdgarFiling] = {}
    for registrant in sec_registrants.registrant_chain(cik):
        for filing in _recent_filings(symbol, registrant, form_type, recent_n):
            by_accession.setdefault(filing.accession, filing)
    newest = sorted(by_accession.values(), key=lambda f: f.filed_at, reverse=True)[:recent_n]
    if not include_text:
        return newest
    return [_with_text(filing) for filing in newest]


def _recent_filings(
    symbol: str, cik: str, form_type: str, recent_n: int
) -> list[EdgarFiling]:
    """One registrant's ``recent_n`` latest ``form_type`` filings, metadata only.

    SEC's submissions JSON lists a registrant's latest filings under
    ``filings.recent`` (a year's at least, or 1,000) and the rest in older
    pages named in ``filings.files``, newest first. A bank that issues
    notes every day fills a year with tens of thousands: JPM's ``recent``
    holds one year, and its 10-K before last is eight pages back. Older
    pages are read, newest first, until ``recent_n`` are found.
    """
    out, older_pages = _from_recent(symbol, cik, form_type, recent_n)
    for name in older_pages:
        if len(out) >= recent_n:
            break
        page = _sec_get(f"https://data.sec.gov/submissions/{name}").json()
        out += _matching(symbol, cik, form_type, page, recent_n - len(out))
    return out


def _from_recent(
    symbol: str, cik: str, form_type: str, recent_n: int
) -> tuple[list[EdgarFiling], list[str]]:
    """The matches in a registrant's ``recent`` filings, and the names of
    the older pages that may hold the rest: those with filings from the
    last ``OLDER_PAGES_YEARS`` before its latest one. Its own function so
    the submissions JSON (5 MB for JPM) is freed before any page is read."""
    filings = _sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json().get("filings", {})
    recent = filings.get("recent", {})
    out = _matching(symbol, cik, form_type, recent, recent_n)
    dates: list[str] = recent.get("filingDate", [])
    if len(out) >= recent_n or not dates:
        return out, []
    horizon = (_parse_iso_date_only(max(dates)) - timedelta(days=365 * OLDER_PAGES_YEARS)).isoformat()
    return out, [p["name"] for p in filings.get("files", []) if p.get("filingTo", "") >= horizon]


def _matching(
    symbol: str, cik: str, form_type: str, block: dict[str, list[Any]], limit: int
) -> list[EdgarFiling]:
    """The first ``limit`` ``form_type`` filings in one block of SEC's
    column-wise filing lists (``recent``, or an older page), which run
    newest first. The form must match exactly: a ``10-K/A`` is not a 10-K."""
    accession_numbers: list[str] = block.get("accessionNumber", [])
    forms: list[str] = block.get("form", [])
    filing_dates: list[str] = block.get("filingDate", [])
    report_dates: list[str] = block.get("reportDate", [])
    primary_docs: list[str] = block.get("primaryDocument", [])
    sizes: list[int] = block.get("size", [])

    out: list[EdgarFiling] = []
    for i, form in enumerate(forms):
        if form != form_type:
            continue
        if len(out) >= limit:
            break
        accession = accession_numbers[i]
        primary = _strip_xsl_prefix(
            primary_docs[i] if i < len(primary_docs) else ""
        )
        out.append(
            EdgarFiling(
                cik=cik,
                symbol=symbol,
                accession=accession,
                form_type=form,
                filed_at=_parse_iso_date(filing_dates[i]),
                period_of_report=_parse_iso_date_only(report_dates[i])
                if i < len(report_dates) and report_dates[i]
                else None,
                primary_doc_url=(
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession.replace('-', '')}/{primary}"
                ),
                size_bytes=sizes[i] if i < len(sizes) else 0,
            )
        )
    return out


def _with_text(filing: EdgarFiling) -> EdgarFiling:
    """``filing`` with its primary document's text; unchanged when the
    filing names no primary document or the fetch fails (text is optional).
    Text already on disk for the accession is reused, not downloaded."""
    if filing.primary_doc_url.endswith("/"):
        return filing
    cached = _read_cached_filing(_cache_root(), filing.cik, filing.accession)
    if cached is not None and cached.primary_doc_text:
        return filing.model_copy(update={"primary_doc_text": cached.primary_doc_text})
    try:
        text = _sec_get(filing.primary_doc_url).text
    except Exception:  # noqa: BLE001 — text is optional, don't kill the call
        return filing
    return filing.model_copy(update={"primary_doc_text": text})


def _parse_iso_date(s: str) -> Any:
    """Parse ``YYYY-MM-DD`` from EDGAR into a tz-aware datetime at UTC midnight."""
    from datetime import UTC, datetime

    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _parse_iso_date_only(s: str) -> Any:
    from datetime import date

    return date.fromisoformat(s)


PROVIDERS: dict[str, EdgarProvider] = {
    "sec": _fetch_edgar_sec,
}


# ── Async entry point ─────────────────────────────────────────────────


async def fetch_edgar(
    symbol: str,
    *,
    form_type: str,
    recent_n: int = 1,
    include_text: bool = False,
    provider: str = "sec",
    cik: str | None = None,
) -> list[EdgarFiling]:
    """
    Fetch the ``recent_n`` most recent ``form_type`` filings for ``symbol``.

    Returns sorted descending by ``filed_at`` (most recent first). The
    provider's last answer is cached for ``INDEX_TTL_SECONDS`` and
    answers any request for as many filings or fewer; otherwise the
    provider is asked. ``include_text=True`` populates
    ``EdgarFiling.primary_doc_text`` (much larger response, only ask
    for it when ``parse_filing`` actually needs the text).

    ``cik`` bypasses the ticker→CIK lookup. Required for institution
    filings (13F-HR), where the filer is an asset manager that doesn't
    appear in SEC's company_tickers.json. ``symbol`` is still required
    as a stable label for ``EdgarFiling.symbol``.
    """
    if form_type not in SUPPORTED_FORM_TYPES:
        raise ValueError(
            f"Unsupported form_type {form_type!r}. "
            f"Supported: {sorted(SUPPORTED_FORM_TYPES)}"
        )
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {provider!r}. Registered: {sorted(PROVIDERS)}"
        )
    target = symbol.upper()
    service_id = f"{provider}.edgar"

    # Trivial-input shortcut. Don't even open a log record — there's
    # genuinely no external call to log.
    if recent_n <= 0:
        return []

    root = _cache_root()
    fetch = PROVIDERS[provider]

    with log_external_call(
        service_id,
        {
            "symbol": target,
            "form_type": form_type,
            "recent_n": recent_n,
            "include_text": include_text,
            "provider": provider,
        },
    ) as call:
        cached = _try_cache(
            root, target, form_type, recent_n, require_text=include_text
        )
        if cached is not None:
            call.record_output(
                {"filing_count": len(cached), "cache_hits": len(cached)}
            )
            return cached

        fetched = await asyncio.to_thread(
            fetch, target, form_type, recent_n, include_text, cik
        )
        newest = sorted(fetched, key=lambda f: f.filed_at, reverse=True)[:recent_n]
        for f in newest:
            _write_filing_to_cache(root, f)
        _write_index(root, target, form_type, recent_n, newest)
        call.record_output({"filing_count": len(newest), "cache_hits": 0})
        return newest


def _try_cache(
    root: Path,
    symbol: str,
    form_type: str,
    recent_n: int,
    *,
    require_text: bool = False,
) -> list[EdgarFiling] | None:
    """The cached answer for the ``recent_n`` newest filings, or None when
    the provider must be asked: the index is missing or stale, it answered
    a request for fewer filings, or a filing it lists is not on disk.

    When ``require_text=True`` (caller passed ``include_text=True``), a
    listed filing without ``primary_doc_text`` is a miss too: otherwise a
    prior metadata-only entry would satisfy a text request and the caller
    would get a filing with no text.
    """
    index = _read_fresh_index(root, symbol, form_type)
    if index is None or recent_n > index["recent_n"]:
        return None
    out: list[EdgarFiling] = []
    for entry in index["filings"][:recent_n]:
        cached = _read_cached_filing(root, entry["cik"], entry["accession"])
        if cached is None or (require_text and not cached.primary_doc_text):
            return None
        out.append(cached)
    return out
