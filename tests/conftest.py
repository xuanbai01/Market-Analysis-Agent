"""
Shared fixtures for the test suite.

Strategy:
- A function-scoped engine points at the configured DATABASE_URL (Postgres
  from docker-compose locally, or the CI job's postgres service). The engine
  uses NullPool so connections never leak across event loops — pytest-asyncio
  gives each test its own loop, and asyncpg connections are bound to the
  loop they were created in. Tables are created/dropped per test from
  SQLAlchemy metadata (not via Alembic — tests bypass migrations). Cost
  is small (3 tiny tables) and in exchange we get bulletproof isolation.
- Each test runs inside an outer connection transaction with
  `join_transaction_mode="create_savepoint"` on the sessionmaker. Any
  `session.commit()` from a route handler commits a SAVEPOINT, and the
  outer `trans.rollback()` at teardown wipes everything.
- The FastAPI `get_session` dependency is overridden to hand out the
  per-test session, and an httpx AsyncClient is wired to the ASGI app.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.dependencies import get_session
from app.db.models.base import Base
from app.db.models.candles import Candle  # noqa: F401  -- registers on Base.metadata
from app.db.models.news import NewsItemModel  # noqa: F401  -- registers on Base.metadata
from app.db.models.news_symbols import NewsSymbol  # noqa: F401  -- registers on Base.metadata
from app.db.models.research_reports import (
    ResearchReportRow,  # noqa: F401  -- registers on Base.metadata
)
from app.db.models.symbols import Symbol  # noqa: F401  -- registers on Base.metadata
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        trans = await connection.begin()
        sessionmaker = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with sessionmaker() as session:
            yield session
        await trans.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """
    An httpx AsyncClient wired straight to the FastAPI app via ASGITransport.
    The `get_session` dependency is overridden to hand out the per-test
    session, so HTTP-driven writes are visible inside the test and discarded
    after it.
    """
    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def anyio_backend() -> str:
    # Some libraries consult this; pytest-asyncio uses asyncio regardless.
    return "asyncio"
