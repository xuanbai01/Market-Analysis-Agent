from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_session
from app.db.models.symbols import Symbol
from app.schemas.symbol import SymbolCreate, SymbolOut


router = APIRouter()


@router.get("/symbols", response_model=list[SymbolOut])
async def list_symbols(
    query: str | None = Query(None, description="Filter by symbol or name"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Symbol).limit(limit)
    if query:
        stmt = stmt.where((Symbol.symbol.ilike(f"%{query}%")) | (Symbol.name.ilike(f"%{query}%")))
    rows = (await session.execute(stmt)).scalars().all()
    return [SymbolOut(symbol=r.symbol, name=r.name) for r in rows]


@router.post("/symbols", response_model=SymbolOut, status_code=201)
async def add_symbol(payload: SymbolCreate, session: AsyncSession = Depends(get_session)):
    sym = Symbol(symbol=payload.symbol.upper(), name=payload.name)
    session.add(sym)
    await session.commit()
    return SymbolOut(symbol=sym.symbol, name=sym.name)