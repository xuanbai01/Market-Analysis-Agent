from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.settings import settings


engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)