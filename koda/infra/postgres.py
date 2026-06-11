import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, func


class Base(DeclarativeBase):
    pass


class ThreadRecord(Base):
    __tablename__ = "threads"

    thread_id = Column(String, primary_key=True)
    org_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    last_message = Column(Text, nullable=True)
    cost_usd = Column(Float, default=0.0)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


def _get_db_url() -> str:
    url = os.getenv("NOEN_CONN_STRING") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL set. Add NOEN_CONN_STRING to .env")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=require" in url:
        url = url.replace("sslmode=require", "ssl=require")
    return url


engine = create_async_engine(
    _get_db_url(),
    echo=False,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)