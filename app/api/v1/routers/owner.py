"""The owner's routes (ADR 0009). Each needs the shared secret and the
owner key (``require_owner``); ``tests/test_owner_auth.py`` pins the set.
They're left out of the public OpenAPI schema, and every response under
``/v1/owner``, errors included, says ``Cache-Control: no-store``
(``app.main``)."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies import require_owner
from app.schemas.owner import OwnerPositions, OwnerStatus
from app.services import tastytrade_client
from app.services.owner_positions import PositionsUnavailable, get_positions

OWNER_PREFIX = "/owner"
router = APIRouter(prefix=OWNER_PREFIX, dependencies=[Depends(require_owner)], include_in_schema=False)


@router.get("/status", response_model=OwnerStatus)
async def owner_status() -> OwnerStatus:
    """Whether the owner's sources are set up; a 200 also says the key is right."""
    return OwnerStatus(tastytrade=tastytrade_client.is_configured())


@router.get("/positions", response_model=OwnerPositions)
async def owner_positions() -> OwnerPositions:
    """The owner's open positions with tastytrade's live quotes, at most 15 s
    old; the last copy, marked stale, when tastytrade fails; 503 with the
    reason when there's none. Never stored."""
    try:
        return await get_positions()
    except PositionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
