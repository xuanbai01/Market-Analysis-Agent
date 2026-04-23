"""
Shared fixtures for the test suite.

Strategy:
- A session-scoped engine points at the configured DATABASE_URL (a Postgres
  instance spun up by docker-compose locally or by the CI job's postgres
  service). Tables are created from SQLAlchemy metadata at session start
  and dropped at session end — no reliance on db/init.sql.
- Each test runs inside a SAVEPOINT that rolls back on teardown, so tests
  are isolated without paying the cost of recreating the schema per test.
- The FastAPI `get_session` dependency is overridden to hand out sessions
  bound to that savepoint, and an httpx AsyncClient is wired to the ASGI
  app (no real socket).
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.dependencies import get_session
from app.db.models.base import Base
# Importing the model classes registers them on Base.metadata so create_all sees them.
from app.db.models.news import NewsItemModel  # noqa: F401
from app.db.models.symbols import Symbol  # noqa: F401
from app.main import app


TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
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
    """
    One transaction per test, rolled back on teardown. Tests can commit
    freely — SQLAlchemy's `begin_nested` gives them a SAVEPOINT inside the
    outer transaction, and the outer `connection.begin()` is the thing
    that gets rolled back.
    """
    async with engine.connect() as connection:
        trans = await connection.begin()
        sessionmaker = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
        await trans.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """
    An httpx AsyncClient wired straight to the FastAPI app via ASGITransport.
    The `get_session` dependency is overridden to hand out the per-test
    rolled-back session, so HTTP-driven writes are visible inside the test
    and discarded after it.
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
