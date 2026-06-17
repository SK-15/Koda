import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, func
from sqlalchemy.pool import NullPool


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
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    url = os.getenv("NOEN_CONN_STRING") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL set. Add NOEN_CONN_STRING to .env")

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # strip query params asyncpg doesn't support — pass ssl via connect_args instead
    parsed = urlparse(url)
    STRIP_PARAMS = {"sslmode", "ssl", "channel_binding", "options"}
    qs = {k: v for k, v in parse_qs(parsed.query).items() if k not in STRIP_PARAMS}
    clean = parsed._replace(query=urlencode(qs, doseq=True))
    return urlunparse(clean)


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _get_db_url(),
            echo=False,
            poolclass=NullPool,
            connect_args={"ssl": "require"},
        )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncSession:
    async with get_session_factory()() as session:
        yield session


async def create_tables():
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
