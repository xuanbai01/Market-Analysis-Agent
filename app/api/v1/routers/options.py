"""Options routes (ADR 0008). Every route needs the shared secret."""
import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    enforce_options_rate_limit,
    enforce_options_read_rate_limit,
    get_session,
)
from app.core.auth import require_shared_secret
from app.schemas.options import ExpiryChain, OptionsRead, OptionsReport, SnapshotRun
from app.services.options_chain import SymbolNotFound
from app.services.options_read import NothingToRead, ReadUnavailable, get_read, has_read
from app.services.options_report import (
    ExpiryNotListed,
    NoUsableQuotes,
    get_chain,
    get_report,
    has_chain,
    is_fresh,
)
from app.services.options_snapshots import SnapshotRunning, run_snapshots

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_shared_secret)])

Symbol = Annotated[str, Path(pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$", description="a ticker, e.g. NVDA or BRK-B")]
_UNAVAILABLE = "Option data is unavailable right now; try again shortly."


async def _limit_misses(request: Request, symbol: str, expiry: date | None = None) -> None:
    """Cached answers are free; anything that asks Yahoo counts (a build is
    about a dozen calls, an expiry not read yet three)."""
    cached = is_fresh(symbol) if expiry is None else has_chain(symbol, expiry)
    if not cached:
        await enforce_options_rate_limit(request)


@router.get("/options/{symbol}", response_model=OptionsReport)
async def options_report(
    request: Request, symbol: Symbol, session: AsyncSession = Depends(get_session)
) -> OptionsReport:
    symbol = symbol.upper()
    await _limit_misses(request, symbol)
    try:
        return await get_report(session, symbol)
    except SymbolNotFound as exc:
        raise HTTPException(status_code=404, detail=f"No such symbol: {symbol}.") from exc
    except Exception as exc:
        logger.exception("options report for %s failed", symbol)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from exc


@router.get("/options/{symbol}/chain/{expiry}", response_model=ExpiryChain)
async def options_chain(
    request: Request, symbol: Symbol, expiry: date, session: AsyncSession = Depends(get_session)
) -> ExpiryChain:
    symbol = symbol.upper()
    await _limit_misses(request, symbol, expiry)
    try:
        return await get_chain(session, symbol, expiry)
    except SymbolNotFound as exc:
        raise HTTPException(status_code=404, detail=f"No such symbol: {symbol}.") from exc
    except ExpiryNotListed as exc:
        raise HTTPException(status_code=404, detail=f"{symbol} lists no options expiring {expiry}.") from exc
    except NoUsableQuotes as exc:
        raise HTTPException(status_code=404, detail=f"No usable quotes for {symbol} expiring {expiry}.") from exc
    except Exception as exc:
        logger.exception("options chain for %s %s failed", symbol, expiry)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from exc


@router.get("/options/{symbol}/read", response_model=OptionsRead)
async def options_read(
    request: Request, symbol: Symbol, session: AsyncSession = Depends(get_session)
) -> OptionsRead:
    """The cited AI read of the symbol's options report. A report build
    counts as a lookup, a read the model has to write as a read."""
    symbol = symbol.upper()
    await _limit_misses(request, symbol)
    try:
        report = await get_report(session, symbol)
    except SymbolNotFound as exc:
        raise HTTPException(status_code=404, detail=f"No such symbol: {symbol}.") from exc
    except Exception as exc:
        logger.exception("options report for %s failed", symbol)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from exc
    # No database connection through the model call (CLAUDE.md): the report
    # committed its view, but a failed history read can leave a transaction
    # open. The session reopens if anything uses it again.
    await session.close()
    # Decided on the report the read is written from, so a rebuild between
    # the two can't make a read free.
    if report.status == "ok" and not has_read(report):
        await enforce_options_read_rate_limit(request)
    try:
        return await get_read(report)
    except NothingToRead as exc:
        raise HTTPException(status_code=404, detail=f"{symbol} has no priced options to read.") from exc
    except ReadUnavailable as exc:
        raise HTTPException(status_code=503, detail="No read could be written just now; try again shortly.") from exc
    except Exception as exc:
        logger.exception("options read for %s failed", symbol)
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from exc


@router.post("/options/snapshots", response_model=SnapshotRun)
async def take_snapshots(session: AsyncSession = Depends(get_session)) -> SnapshotRun:
    """Store today's IV snapshot for each tracked ticker; the daily cron's
    target. Idempotent: a ticker already stored for the session is skipped."""
    try:
        return await run_snapshots(session)
    except SnapshotRunning as exc:
        raise HTTPException(status_code=409, detail="A snapshot run is already in progress.") from exc
