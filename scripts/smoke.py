"""Run each Phase 2 read-only tool against a real ticker.

No DB, no LLM. Validates that live providers (yfinance, SEC EDGAR, FRED)
still return data shapes the parsers understand. Mocked unit tests
cannot catch upstream schema drift; this script can.

Usage:
    uv run python scripts/smoke.py            # defaults to AAPL
    uv run python scripts/smoke.py NVDA
    uv run python scripts/smoke.py AAPL --skip-13f --form-4-n 5

Exit code is 0 only when every non-skipped tool returns successfully.
The 13F runner fans out across the curated institution list and is
the slowest; ``--skip-13f`` is provided for fast iteration. Output is
intentionally compact — it's a spot-check, not a test report.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``app.*`` importable when invoked as ``python scripts/smoke.py``.
# The repo root is one level up from this file. Editable-installing the
# project (``uv pip install -e .``) would make this unnecessary, but
# this script is meant to work on a fresh clone with just ``uv sync``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import time  # noqa: E402
from collections.abc import Awaitable, Callable  # noqa: E402
from typing import Any  # noqa: E402

from app.core.settings import settings  # noqa: E402

# ── Output primitives ─────────────────────────────────────────────────
# ASCII + a few unicode glyphs. No ANSI colors so the script renders the
# same on Windows cmd.exe, Git Bash, and CI. Compactness over prettiness.


def _hdr(name: str) -> None:
    print(f"\n── {name}")


def _ok(latency_ms: float, summary: str) -> None:
    print(f"  ok    {latency_ms:>6.0f} ms  {summary}")


def _skip(reason: str) -> None:
    print(f"  skip  {' ' * 9}  {reason}")


def _fail(latency_ms: float, exc: BaseException) -> None:
    print(f"  FAIL  {latency_ms:>6.0f} ms  {type(exc).__name__}: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────


def _claim_preview(result: dict[str, Any], n: int = 3) -> str:
    """First N entries of a ``dict[str, Claim]`` formatted as ``key=value``."""
    items = list(result.items())[:n]
    parts = [f"{k}={getattr(c, 'value', c)!r}" for k, c in items]
    extra = max(0, len(result) - n)
    suffix = f" +{extra} more" if extra else ""
    return f"{len(result)} claims  ({', '.join(parts)}{suffix})"


async def _run(
    name: str,
    coro: Awaitable[Any],
    summarize: Callable[[Any], str],
) -> bool:
    """Run one tool, time it, print one line per outcome."""
    _hdr(name)
    start = time.perf_counter()
    try:
        result = await coro
    except Exception as exc:  # noqa: BLE001 — smoke surfaces every failure
        _fail((time.perf_counter() - start) * 1000, exc)
        return False
    _ok((time.perf_counter() - start) * 1000, summarize(result))
    return True


# ── Per-tool runners ──────────────────────────────────────────────────
#
# Each runner is async and lazy-imports its tool. A missing optional
# provider dep won't break the rest of the smoke. Returns True on
# success, False on failure, None on skip.


async def smoke_fundamentals(symbol: str) -> bool:
    from app.services.fundamentals import fetch_fundamentals

    return await _run(
        "fetch_fundamentals",
        fetch_fundamentals(symbol),
        _claim_preview,
    )


async def smoke_peers(symbol: str) -> bool:
    from app.services.peers import fetch_peers

    return await _run(
        "fetch_peers",
        fetch_peers(symbol),
        _claim_preview,
    )


async def smoke_edgar(symbol: str) -> bool:
    from app.services.edgar import fetch_edgar

    def _summary(filings: list[Any]) -> str:
        if not filings:
            return "no filings"
        f = filings[0]
        return f"{len(filings)} filing(s)  ({f.accession}  filed {f.filed_at:%Y-%m-%d})"

    return await _run(
        "fetch_edgar (10-K, n=1)",
        fetch_edgar(symbol, form_type="10-K", recent_n=1),
        _summary,
    )


async def smoke_form_4(symbol: str, recent_n: int) -> bool:
    from app.services.form_4 import parse_form_4_cluster

    return await _run(
        f"parse_form_4_cluster (n={recent_n})",
        parse_form_4_cluster(symbol, recent_n=recent_n),
        _claim_preview,
    )


async def smoke_13f(symbol: str) -> bool:
    from app.services.holdings_13f import parse_13f_holdings

    return await _run(
        "parse_13f_holdings",
        parse_13f_holdings(symbol),
        _claim_preview,
    )


async def smoke_10k_business(symbol: str) -> bool:
    from app.services.ten_k import extract_10k_business

    def _summary(r: Any) -> str:
        if r is None:
            return "no extraction"
        return f"{r.char_count:>6,} chars  ({r.accession}  filed {r.filed_at:%Y-%m-%d})"

    return await _run(
        "extract_10k_business",
        extract_10k_business(symbol),
        _summary,
    )


async def smoke_10k_risks(symbol: str) -> bool:
    from app.services.ten_k import extract_10k_risks

    def _summary(r: Any) -> str:
        if r is None:
            return "no extraction"
        return f"{r.char_count:>6,} chars  ({r.accession}  filed {r.filed_at:%Y-%m-%d})"

    return await _run(
        "extract_10k_risks",
        extract_10k_risks(symbol),
        _summary,
    )


async def smoke_10k_risks_diff(symbol: str) -> bool:
    from app.services.ten_k import extract_10k_risks_diff

    def _summary(r: Any) -> str:
        if r is None:
            return "no diff (need ≥2 10-Ks)"
        return (
            f"+{len(r.added_paragraphs)} new  "
            f"-{len(r.removed_paragraphs)} dropped  "
            f"={r.kept_paragraph_count} kept  "
            f"Δ{r.char_delta:+,} chars"
        )

    return await _run(
        "extract_10k_risks_diff",
        extract_10k_risks_diff(symbol),
        _summary,
    )


async def smoke_earnings(symbol: str) -> bool:
    from app.services.earnings import fetch_earnings

    return await _run(
        "fetch_earnings",
        fetch_earnings(symbol),
        _claim_preview,
    )


async def smoke_macro(symbol: str) -> bool | None:
    if not settings.FRED_API_KEY:
        _hdr("fetch_macro")
        _skip("FRED_API_KEY not set (set in .env to enable)")
        return None
    from app.services.macro import fetch_macro

    return await _run(
        "fetch_macro",
        fetch_macro(symbol),
        _claim_preview,
    )


# ── Orchestration ─────────────────────────────────────────────────────


async def main(
    symbol: str,
    *,
    skip_13f: bool,
    skip_form_4: bool,
    form_4_n: int,
) -> int:
    print("=" * 68)
    print(f"  Smoke test  ·  symbol={symbol}  ·  EDGAR cache={settings.EDGAR_CACHE_DIR}")
    print("=" * 68)

    results: list[bool | None] = []

    # Fast tools first (yfinance), so a failure surfaces quickly.
    results.append(await smoke_fundamentals(symbol))
    results.append(await smoke_peers(symbol))
    results.append(await smoke_earnings(symbol))
    results.append(await smoke_macro(symbol))

    # Then EDGAR-backed (disk-cached, but first run is slow).
    results.append(await smoke_edgar(symbol))
    results.append(await smoke_10k_business(symbol))
    results.append(await smoke_10k_risks(symbol))
    results.append(await smoke_10k_risks_diff(symbol))

    if skip_form_4:
        _hdr("parse_form_4_cluster")
        _skip("--skip-form-4 set")
        results.append(None)
    else:
        results.append(await smoke_form_4(symbol, recent_n=form_4_n))

    if skip_13f:
        _hdr("parse_13f_holdings")
        _skip("--skip-13f set (slow — fans out across curated institutions)")
        results.append(None)
    else:
        results.append(await smoke_13f(symbol))

    ok = sum(1 for r in results if r is True)
    skipped = sum(1 for r in results if r is None)
    failed = sum(1 for r in results if r is False)
    print()
    print("=" * 68)
    print(f"  Summary  ·  ok={ok}  skip={skipped}  FAIL={failed}  of {len(results)} tools")
    print("=" * 68)
    print()

    return 0 if failed == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test every Phase 2 read-only tool against a real ticker.",
    )
    parser.add_argument(
        "symbol", nargs="?", default="AAPL", help="ticker symbol (default: AAPL)"
    )
    parser.add_argument(
        "--skip-13f",
        action="store_true",
        help="skip the 13F holdings smoke (fans out across many SEC filings)",
    )
    parser.add_argument(
        "--skip-form-4", action="store_true", help="skip the Form 4 cluster smoke"
    )
    parser.add_argument(
        "--form-4-n",
        type=int,
        default=10,
        help="recent_n for parse_form_4_cluster (default 10; production default is 50)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(
        asyncio.run(
            main(
                args.symbol.upper(),
                skip_13f=args.skip_13f,
                skip_form_4=args.skip_form_4,
                form_4_n=args.form_4_n,
            )
        )
    )
