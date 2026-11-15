"""The owner's routes (ADR 0009). Each needs the shared secret and the
owner key (``require_owner``); ``tests/test_owner_auth.py`` pins the set.
They're left out of the public OpenAPI schema."""
from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.v1.dependencies import require_owner
from app.schemas.owner import OwnerPositions, OwnerStatus
from app.services import tastytrade_client
from app.services.owner_positions import PositionsUnavailable, get_positions

router = APIRouter(prefix="/owner", dependencies=[Depends(require_owner)], include_in_schema=False)
# The owner's account data never sits in a browser's or a proxy's cache.
_NO_STORE = {"Cache-Control": "no-store"}


@router.get("/status", response_model=OwnerStatus)
async def owner_status() -> OwnerStatus:
    """Whether the owner's sources are set up; a 200 also says the key is right."""
    return OwnerStatus(tastytrade=tastytrade_client.is_configured())


@router.get("/positions", response_model=OwnerPositions)
async def owner_positions(response: Response) -> OwnerPositions:
    """The owner's open positions with tastytrade's live quotes, at most 15 s
    old; the last copy, marked stale, when tastytrade fails; 503 with the
    reason when there's none. Never stored."""
    response.headers.update(_NO_STORE)
    try:
        return await get_positions()
    except PositionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers=_NO_STORE) from exc
