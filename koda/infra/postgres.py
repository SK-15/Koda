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


engine = create_async_engine(
    os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/koda"),
    echo=False,
    pool_size=10,
    max_overflow=20,
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