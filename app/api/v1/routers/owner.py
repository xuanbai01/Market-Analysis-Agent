"""The owner's routes (ADR 0009). Each needs the shared secret and the
owner key (``require_owner``); ``tests/test_owner_auth.py`` pins the set.
They're left out of the public OpenAPI schema."""
from fastapi import APIRouter, Depends

from app.api.v1.dependencies import require_owner
from app.schemas.owner import OwnerStatus
from app.services import tastytrade_client

router = APIRouter(prefix="/owner", dependencies=[Depends(require_owner)], include_in_schema=False)


@router.get("/status", response_model=OwnerStatus)
async def owner_status() -> OwnerStatus:
    """Whether the owner's sources are set up; a 200 also says the key is right."""
    return OwnerStatus(tastytrade=tastytrade_client.is_configured())
