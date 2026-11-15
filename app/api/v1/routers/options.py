"""Options routes (ADR 0008). Every route needs the shared secret."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session
from app.core.auth import require_shared_secret
from app.schemas.options import SnapshotRun
from app.services.options_snapshots import SnapshotRunning, run_snapshots

router = APIRouter(dependencies=[Depends(require_shared_secret)])


@router.post("/options/snapshots", response_model=SnapshotRun)
async def take_snapshots(session: AsyncSession = Depends(get_session)) -> SnapshotRun:
    """Store today's IV snapshot for each tracked ticker; the daily cron's
    target. Idempotent: a ticker already stored for the session is skipped."""
    try:
        return await run_snapshots(session)
    except SnapshotRunning as exc:
        raise HTTPException(status_code=409, detail="A snapshot run is already in progress.") from exc
