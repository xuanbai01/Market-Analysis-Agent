from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.dependencies import get_session
from pydantic import BaseModel


router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    db: bool


@router.get("/health", response_model=HealthResponse, summary="Liveness and DB check")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return HealthResponse(status="ok", db=db_ok)