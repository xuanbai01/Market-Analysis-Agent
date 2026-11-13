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

    {EDGAR_CACHE_DIR}/{cik}/{accession}/metadata.json    — EdgarFiling JSON
    {EDGAR_CACHE_DIR}/{cik}/{accession}/{filename}        — primary doc text
    {EDGAR_CACHE_DIR}/{symbol}/{form_type}.json           — accession index

The ``{symbol}/{form_type}.json`` index is what lets us answer "give me
the most recent 3 10-Ks for AAPL" without re-hitting EDGAR's submissions
endpoint. On a cache miss we write through both the per-filing
metadata AND update the per-(symbol, form_type) index.

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
had cached two 10-Ks never saw a third).
Both rules are documented at
https://www.sec.gov/os/accessing-edgar-data.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections.abc import Callable
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


def _read_cached_index(root: Path, symbol: str, form_type: str) -> list[dict[str, str]]:
    """Read the accession index for a (symbol, form_type); [] if absent or unreadable."""
    idx = _index_path(root, symbol, form_type)
    if not idx.exists():
        return []
    try:
        return json.loads(idx.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — corrupt index → treat as empty
        return []


def _write_filing_to_cache(root: Path, filing: EdgarFiling) -> None:
    """Cache one filing's metadata + extend the per-(symbol, form_type) index."""
    cache_dir = _cache_key_dir(root, filing.cik, filing.accession)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(cache_dir / "metadata.json", filing.model_dump_json())

    # Update the index. Read-modify-write isn't atomic across concurrent
    # callers; that's an acceptable trade-off for a cache (worst case is
    # a duplicate accession in the list, which we de-dup on read).
    index = _read_cached_index(root, filing.symbol, filing.form_type)
    entry = {"cik": filing.cik, "accession": filing.accession}
    if entry not in index:
        index.append(entry)
    _atomic_write(_index_path(root, filing.symbol, filing.form_type), json.dumps(index))


# ── Production provider — SEC HTTP ────────────────────────────────────
# Not unit-tested in the suite; exercised post-merge via a smoke test.
# Kept defensive (any HTTP / parsing failure raises) so the async entry
# point's log_external_call records the outcome accurately.


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
    """One registrant's ``recent_n`` latest ``form_type`` filings, metadata only."""
    submissions = _sec_get(
        f"https://data.sec.gov/submissions/CIK{cik}.json"
    ).json()
    recent = submissions.get("filings", {}).get("recent", {})

    accession_numbers: list[str] = recent.get("accessionNumber", [])
    forms: list[str] = recent.get("form", [])
    filing_dates: list[str] = recent.get("filingDate", [])
    report_dates: list[str] = recent.get("reportDate", [])
    primary_docs: list[str] = recent.get("primaryDocument", [])
    sizes: list[int] = recent.get("size", [])

    out: list[EdgarFiling] = []
    for i, form in enumerate(forms):
        if form != form_type:
            continue
        if len(out) >= recent_n:
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

    Returns sorted descending by ``filed_at`` (most recent first). Disk
    cache is checked first; on a hit, the provider is not called for
    the cached subset. ``include_text=True`` populates
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
        cache_hits = len(cached)
        provider_filings: list[EdgarFiling] = []

        # Cache satisfied the request entirely → skip the provider.
        if cache_hits < recent_n:
            provider_filings = await asyncio.to_thread(
                fetch, target, form_type, recent_n, include_text, cik
            )
            for f in provider_filings:
                _write_filing_to_cache(root, f)

        merged = _merge_and_sort(cached, provider_filings, recent_n)
        call.record_output(
            {"filing_count": len(merged), "cache_hits": cache_hits}
        )
        return merged


def _try_cache(
    root: Path,
    symbol: str,
    form_type: str,
    recent_n: int,
    *,
    require_text: bool = False,
) -> list[EdgarFiling]:
    """Read up to ``recent_n`` cached filings for (symbol, form_type).

    When ``require_text=True`` (caller passed ``include_text=True``), a
    cached entry whose ``primary_doc_text`` is None counts as a miss —
    the provider must be invoked to fetch the text. Without this gate, a
    prior metadata-only cache entry silently satisfies a text request
    and the caller receives a useless empty-text filing.
    """
    path = _index_path(root, symbol, form_type)
    if not path.exists() or time.time() - path.stat().st_mtime > INDEX_TTL_SECONDS:
        return []  # no index, or too old to say what the latest filings are
    index = _read_cached_index(root, symbol, form_type)
    out: list[EdgarFiling] = []
    for entry in index:
        if len(out) >= recent_n:
            break
        cached = _read_cached_filing(root, entry["cik"], entry["accession"])
        if cached is None:
            continue
        if require_text and not cached.primary_doc_text:
            continue
        out.append(cached)
    return out


def _merge_and_sort(
    cached: list[EdgarFiling],
    fresh: list[EdgarFiling],
    recent_n: int,
) -> list[EdgarFiling]:
    """Combine cache + provider results, dedupe by accession, sort newest-first."""
    seen: dict[str, EdgarFiling] = {}
    for f in (*cached, *fresh):
        seen[f.accession] = f  # later entries win (provider freshness > cache)
    ordered = sorted(seen.values(), key=lambda f: f.filed_at, reverse=True)
    return ordered[:recent_n]
