from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings

# `pool_pre_ping=True` runs a tiny `SELECT 1` before handing out a pooled
# connection. Cheap insurance against "server closed the connection
# unexpectedly" when Neon's autosuspend drops idle connections after
# ~5 min of inactivity; SQLAlchemy transparently reconnects.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
