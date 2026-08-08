# Persistent Chat Checkpointer (Postgres) Design

**Goal:** Chat message history currently lives only in the FastAPI process's RAM (LangGraph's `MemorySaver`) and is lost on every restart. Replace it with LangGraph's `AsyncPostgresSaver`, backed by the same Neon Postgres database koda already uses for users, threads, and provider keys, so chat history survives restarts.

**Non-goals:** No change to any HTTP/WS API contract. No frontend changes. No migration of old chat history (there is none to migrate — it was never persisted). No horizontal-scaling story beyond what Postgres already gives us "for free" (any process can now resume any thread_id, since state is centralized instead of per-process RAM).

## Current State

- `agent/graph.py:build_graph(checkpointer=None)` defaults to `MemorySaver()` when no checkpointer is passed.
- `api/main.py`'s `lifespan` calls `build_graph()` with **no** checkpointer argument, so it's always `MemorySaver` today — despite a stale comment on `agent/graph.py`'s `compiled_graph` line claiming a Redis checkpointer is used. Redis is connected in the same lifespan but is only ever used for 1-hour task-status polling (`infra/task_store.py`), never for graph state.
- Postgres already durably stores chat *metadata* (`ThreadRecord`: title, truncated `last_message`, cost, timestamps) via `infra/chats_repo.py` — just not the actual message content.
- `create_tables()` (`infra/postgres.py`), which creates koda's own SQLAlchemy-managed tables, is never called automatically at app startup — only from the one-off `scripts/create_user.py` CLI script. This is the existing convention for schema setup in this codebase.

## Architecture

Swap the checkpointer LangGraph uses from `MemorySaver` to `AsyncPostgresSaver` (new dependency: `langgraph-checkpoint-postgres`), pointed at the same Neon database via a plain psycopg (v3) DSN. Opened once in `api/main.py`'s `lifespan`, mirroring how the Redis client is opened today, and passed into the existing `build_graph(checkpointer=...)` parameter — `build_graph`'s signature and internals don't change.

Table setup for the checkpointer's own tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations`) is a manual one-off via a new `scripts/setup_checkpointer.py`, run once before first deploying this change — following the same "not automatic on every boot" convention `create_tables()` already uses.

## Components

### `infra/postgres.py` — new `_get_psycopg_dsn()`

The existing `_get_db_url()` returns a SQLAlchemy/asyncpg DSN (`postgresql+asyncpg://...`, with `sslmode`/`ssl`/`channel_binding`/`options` query params stripped, since asyncpg takes TLS via `connect_args={"ssl": "require"}` instead of the DSN). psycopg v3 wants a plain `postgresql://...` DSN with `sslmode=require` present in the query string itself.

`_get_psycopg_dsn()` reuses the same `NOEN_CONN_STRING`/`DATABASE_URL` env var, but:
- Leaves the scheme as `postgresql://` (no `+asyncpg` suffix).
- Strips the same SQLAlchemy-irrelevant params (`ssl`, `channel_binding`, `options`) but keeps/adds `sslmode=require`.

### `api/main.py` — lifespan wiring

```python
from contextlib import AsyncExitStack
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from infra.postgres import _get_psycopg_dsn

@asynccontextmanager
async def lifespan(app: FastAPI):
    import agent.graph as agent_graph
    from agent.graph import build_graph
    from infra.redis_client import get_redis, close_redis

    app.state.redis = await get_redis()

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(_get_psycopg_dsn())
        )
        agent_graph.compiled_graph = build_graph(checkpointer=checkpointer)
        yield

    await close_redis()
```

(`AsyncExitStack` cleanly closes the connection pool on shutdown, symmetric with `close_redis()`.)

Also: fix the stale comment on `agent/graph.py`'s `compiled_graph = None` line — it currently claims a Redis checkpointer, which was never accurate; update it to say Postgres.

### `scripts/setup_checkpointer.py` — new, one-off

Same minimal CLI style as `scripts/create_user.py`:

```python
"""One-time setup for the LangGraph Postgres checkpointer's tables.

Usage:
    uv run python -m scripts.setup_checkpointer
"""
import asyncio
from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from infra.postgres import _get_psycopg_dsn  # noqa: E402


async def main() -> None:
    async with AsyncPostgresSaver.from_conn_string(_get_psycopg_dsn()) as checkpointer:
        await checkpointer.setup()
    print("Checkpointer tables ready.")


if __name__ == "__main__":
    asyncio.run(main())
```

## Data Flow

Unchanged from the outside. `POST /api/v1/chats/{chat_id}/messages` and `GET /api/v1/chats/{chat_id}` don't change — the checkpointer is an implementation detail entirely behind `get_compiled_graph()`. No frontend changes, no API contract changes.

## Error Handling

No new failure mode beyond "Postgres is unreachable," which already takes down every other route in the app today via the SQLAlchemy engine. The checkpointer shares fate with the rest of the system rather than introducing a new single point of failure.

## Testing

- Unit test `_get_psycopg_dsn()`: pure string transformation, no DB needed — mock `NOEN_CONN_STRING`/`DATABASE_URL` env var, assert the returned DSN has `postgresql://` scheme (not `+asyncpg`) and `sslmode=require` present, and that `ssl`/`channel_binding`/`options` are stripped.
- The lifespan wiring itself (opening a real `AsyncPostgresSaver` pool) is an integration concern requiring a live Postgres — verified manually per `TESTING.md`'s existing "Level 3 — Full stack" pattern: start the server, send a chat message, restart the server, confirm `GET /chats/{chat_id}` still returns the prior messages. Not added as an automated pytest requiring a live DB in CI.

## Global Constraints

- New dependency: `langgraph-checkpoint-postgres` (pulls in `psycopg[binary]`/`psycopg-pool` transitively).
- `create_tables()`-style schema setup stays manual/one-off — do not call `checkpointer.setup()` automatically at app startup.
- No API/contract changes, no frontend changes.
- No migration of prior chat history (none exists to migrate).
