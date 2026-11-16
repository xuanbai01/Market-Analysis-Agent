"""The owner's routes (ADR 0009). Each needs the shared secret and the
owner key (``require_owner``); ``tests/test_owner_auth.py`` pins the set.
They're left out of the public OpenAPI schema, and every response under
``/v1/owner``, errors included, says ``Cache-Control: no-store``
(``app.main``)."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session, require_owner
from app.schemas.owner import LiveChain, OwnerPositions, OwnerStatus, OwnerTrades
from app.services import owner_vault, tastytrade_client
from app.services.owner_live_chain import LiveChainUnavailable, NotListed, live_chain
from app.services.owner_positions import PositionsUnavailable, get_positions
from app.services.owner_trades import SyncFailed, csv_text, list_trades, sync
from app.services.trade_journal import journal_of

OWNER_PREFIX = "/owner"
# Tighter than the options routes': one class separator at most, so the
# ticker always maps to a path tastytrade's client allows (BRK-B is BRK/B).
Symbol = Annotated[str, Path(pattern=r"^[A-Za-z][A-Za-z0-9]{0,9}(?:[.\-][A-Za-z0-9]{1,4})?$", description="a ticker, e.g. NVDA or BRK-B")]
router = APIRouter(prefix=OWNER_PREFIX, dependencies=[Depends(require_owner)], include_in_schema=False)


@router.get("/status", response_model=OwnerStatus)
async def owner_status() -> OwnerStatus:
    """Whether the owner's sources are set up; a 200 also says the key is right."""
    return OwnerStatus(tastytrade=tastytrade_client.is_configured(), vault=owner_vault.is_configured())


@router.get("/positions", response_model=OwnerPositions)
async def owner_positions() -> OwnerPositions:
    """The owner's open positions with tastytrade's live quotes, at most 15 s
    old; the last copy, marked stale, when tastytrade fails; 503 with the
    reason when there's none. Never stored."""
    try:
        return await get_positions()
    except PositionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/trades", response_model=OwnerTrades)
async def owner_trades(session: AsyncSession = Depends(get_session)) -> OwnerTrades:
    """The owner's trades from the encrypted copy, synced from tastytrade
    first (at most once a minute), and read as a journal (``trade_journal``,
    never stored). When tastytrade can't be reached, the copy as it stands,
    saying why; 503 without the vault key."""
    synced, reason = True, None
    try:
        await sync(session)
    except owner_vault.VaultUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SyncFailed as exc:
        synced, reason = False, str(exc)
    try:
        trades = await list_trades(session)
    except owner_vault.VaultUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return OwnerTrades(trades=trades, synced=synced, reason=reason, journal=await journal_of(trades))


@router.get("/trades.csv")
async def owner_trades_csv(session: AsyncSession = Depends(get_session)) -> Response:
    """The stored copy as CSV, to keep: text a spreadsheet would run as a
    formula is prefixed with ' (``owner_trades.csv_cell``)."""
    try:
        trades = await list_trades(session)
    except owner_vault.VaultUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=csv_text(trades),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="trades.csv"'},
    )


@router.get("/options/{symbol}/live/{expiry}", response_model=LiveChain)
async def owner_live_chain(symbol: Symbol, expiry: date) -> LiveChain:
    """One expiry's chain at tastytrade's live quotes, at most 10 s old; 422
    when tastytrade lists no such expiry, 503 with the reason otherwise.
    Never stored, never sent to the options read."""
    symbol = symbol.upper()
    try:
        return await live_chain(symbol, expiry)
    except NotListed as exc:
        # 422, not 404: the page reads a 404 from an owner route as "no
        # owner key on the server" and would forget the key.
        raise HTTPException(status_code=422, detail=f"tastytrade lists no {symbol} options expiring {expiry}.") from exc
    except LiveChainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

