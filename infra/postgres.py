import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, func, UniqueConstraint
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    project_id     = Column(String, primary_key=True)
    org_id         = Column(String, nullable=False)
    user_id        = Column(String, nullable=False)
    name           = Column(String, nullable=False)
    workspace_path = Column(String, nullable=False)
    created_at     = Column(DateTime, server_default=func.now())
    updated_at     = Column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    user_id       = Column(String, primary_key=True)
    email         = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=True)
    created_at    = Column(DateTime, server_default=func.now())


class ThreadRecord(Base):
    __tablename__ = "threads"

    thread_id    = Column(String, primary_key=True)
    org_id       = Column(String, nullable=False)
    user_id      = Column(String, nullable=False)
    project_id   = Column(String, nullable=True)
    title        = Column(String, nullable=True)
    last_message = Column(Text, nullable=True)
    cost_usd     = Column(Float, default=0.0)
    tokens_used  = Column(Integer, default=0)
    created_at   = Column(DateTime, server_default=func.now())
    updated_at   = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UserProviderKey(Base):
    __tablename__ = "user_provider_keys"

    id                = Column(String, primary_key=True)
    user_id           = Column(String, nullable=False, index=True)
    alias             = Column(String, nullable=False)
    provider_kind     = Column(String, nullable=False)
    api_key_encrypted = Column(Text, nullable=False)
    base_url          = Column(String, nullable=True)
    created_at        = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "alias", name="uq_user_provider_alias"),)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id          = Column(String, primary_key=True)
    user_id     = Column(String, nullable=False, index=True)
    family_id   = Column(String, nullable=False, index=True)
    token_hash  = Column(String, nullable=False, unique=True)
    expires_at  = Column(DateTime, nullable=False)
    created_at  = Column(DateTime, server_default=func.now())
    revoked_at  = Column(DateTime, nullable=True)


def _get_db_url() -> str:
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    url = os.getenv("NOEN_CONN_STRING") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL set. Add NOEN_CONN_STRING to .env")

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    STRIP_PARAMS = {"sslmode", "ssl", "channel_binding", "options"}
    qs = {k: v for k, v in parse_qs(parsed.query).items() if k not in STRIP_PARAMS}
    clean = parsed._replace(query=urlencode(qs, doseq=True))
    return urlunparse(clean)


def _get_psycopg_dsn() -> str:
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

    url = os.getenv("NOEN_CONN_STRING") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL set. Add NOEN_CONN_STRING to .env")

    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    parsed = urlparse(url)
    STRIP_PARAMS = {"ssl", "channel_binding", "options"}
    qs = {k: v for k, v in parse_qs(parsed.query).items() if k not in STRIP_PARAMS}
    qs["sslmode"] = ["require"]
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
