# Persistent Chat Checkpointer (Postgres) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LangGraph's in-process `MemorySaver` with `AsyncPostgresSaver`, backed by koda's existing Neon Postgres database, so chat message history survives process restarts instead of living only in RAM.

**Architecture:** `agent/graph.py:build_graph(checkpointer=None)` already accepts a checkpointer and only needs one passed in. `api/main.py`'s `lifespan` opens an `AsyncPostgresSaver` once (mirroring how it already opens the Redis client) and passes it to `build_graph()`. A new `infra/postgres.py:_get_psycopg_dsn()` derives the psycopg-v3-compatible DSN from the same env var the existing SQLAlchemy engine uses. The checkpointer's own tables are created by a new one-off script, not automatically at every app boot — matching the existing convention for `create_tables()`.

**Tech Stack:** LangGraph (`langgraph-checkpoint-postgres`, new dependency), psycopg v3 (pulled in transitively), FastAPI lifespan, pytest.

## Global Constraints

- New dependency: `langgraph-checkpoint-postgres` (pulls in `psycopg[binary]`/`psycopg-pool` transitively). Add via `uv add`, not by hand-editing `uv.lock`.
- `create_tables()`-style schema setup stays manual/one-off — do not call `checkpointer.setup()` automatically at app startup.
- No API/contract changes, no frontend changes.
- No migration of prior chat history (none exists to migrate — it was never persisted).
- This project uses `uv` — run all Python commands as `uv run ...`.
- `NOEN_CONN_STRING` (or `DATABASE_URL`) in `.env` is the one source of DB connection info — both the existing SQLAlchemy/asyncpg DSN and the new psycopg DSN derive from it.

---

### Task 1: `_get_psycopg_dsn()` helper in `infra/postgres.py`

**Files:**
- Modify: `infra/postgres.py`
- Test: `tests/test_koda.py` (new `TestPsycopgDsn` class, place after `class TestOrmModels` ends at line 502, before the `# ── Auth ...` section comment at line 505)

**Interfaces:**
- Produces: `_get_psycopg_dsn() -> str` in `infra/postgres.py` — a later task (Task 3 and Task 4) calls this to get a psycopg-v3-compatible connection string.

The existing `_get_db_url()` (already in `infra/postgres.py:74-88`) returns a SQLAlchemy/asyncpg DSN (`postgresql+asyncpg://...`) with `sslmode`/`ssl`/`channel_binding`/`options` query params stripped, because asyncpg takes TLS via `connect_args={"ssl": "require"}` (see `get_engine()`, `infra/postgres.py:95-104`) rather than the DSN itself. psycopg v3 (used by `langgraph-checkpoint-postgres`) wants a plain `postgresql://...` DSN with `sslmode=require` present in the query string.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_koda.py`, immediately after `class TestOrmModels` (after the `test_user_provider_key_model_has_fields` method, before the `# ── Auth ...` comment):

```python
# ── Psycopg DSN (LangGraph Postgres checkpointer) ───────────────────────────────

class TestPsycopgDsn:
    def test_strips_asyncpg_suffix(self, monkeypatch):
        monkeypatch.setenv("NOEN_CONN_STRING", "postgresql+asyncpg://user:pw@host/db")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from infra.postgres import _get_psycopg_dsn
        dsn = _get_psycopg_dsn()
        assert dsn.startswith("postgresql://")
        assert "+asyncpg" not in dsn

    def test_adds_sslmode_require_when_absent(self, monkeypatch):
        monkeypatch.setenv("NOEN_CONN_STRING", "postgresql://user:pw@host/db")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from infra.postgres import _get_psycopg_dsn
        dsn = _get_psycopg_dsn()
        assert "sslmode=require" in dsn

    def test_strips_asyncpg_only_params_but_keeps_sslmode(self, monkeypatch):
        monkeypatch.setenv(
            "NOEN_CONN_STRING",
            "postgresql://user:pw@host/db?sslmode=require&channel_binding=require&options=x",
        )
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from infra.postgres import _get_psycopg_dsn
        dsn = _get_psycopg_dsn()
        assert "sslmode=require" in dsn
        assert "channel_binding" not in dsn
        assert "options" not in dsn

    def test_raises_when_no_db_url_set(self, monkeypatch):
        monkeypatch.delenv("NOEN_CONN_STRING", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from infra.postgres import _get_psycopg_dsn
        import pytest
        with pytest.raises(RuntimeError):
            _get_psycopg_dsn()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_koda.py::TestPsycopgDsn -v`
Expected: FAIL with `ImportError: cannot import name '_get_psycopg_dsn'` (the function doesn't exist yet).

- [ ] **Step 3: Implement `_get_psycopg_dsn()`**

Add to `infra/postgres.py`, directly below the existing `_get_db_url()` function (after line 88):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_koda.py::TestPsycopgDsn -v`
Expected: PASS (4/4).

- [ ] **Step 5: Commit**

```bash
git add infra/postgres.py tests/test_koda.py
git commit -m "feat: add psycopg DSN helper for the Postgres checkpointer"
```

---

### Task 2: Add `langgraph-checkpoint-postgres` dependency, remove the stale `langgraph-checkpoint-redis` reference

**Files:**
- Modify: `pyproject.toml` (via `uv add`, not hand-edited)
- Modify: `requirements.txt:9`
- Modify: `uv.lock` (auto-updated by `uv add`)

**Interfaces:**
- Produces: the `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` class becomes importable — Task 3 and Task 4 both `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`.

`requirements.txt:9` currently has `langgraph-checkpoint-redis>=0.0.1` — a leftover from an earlier, never-completed attempt at Redis-backed checkpointing (it's not in `pyproject.toml` or `uv.lock` at all, and nothing in the codebase imports it; it's also the likely origin of the stale `agent/graph.py:52` comment claiming "Redis checkpointer", fixed in Task 4). Since this plan replaces that abandoned direction with Postgres, remove the dead line rather than leave two contradictory checkpointer references sitting in the dependency manifests.

- [ ] **Step 1: Add the new dependency**

Run: `uv add langgraph-checkpoint-postgres`

This updates `pyproject.toml`'s `dependencies` list and `uv.lock` automatically.

- [ ] **Step 2: Remove the stale Redis-checkpoint line from `requirements.txt`**

In `requirements.txt`, change:

```
# Agent framework
langgraph>=0.2.0
langgraph-checkpoint-redis>=0.0.1
langchain-core>=0.2.0
langchain-anthropic>=0.1.0
```

to:

```
# Agent framework
langgraph>=0.2.0
langgraph-checkpoint-postgres>=2.0.0
langchain-core>=0.2.0
langchain-anthropic>=0.1.0
```

(Match whatever version `uv add` resolved into `pyproject.toml` in Step 1 — use that exact lower bound here instead of `2.0.0` if it differs.)

- [ ] **Step 3: Verify the package imports cleanly**

Run: `uv run python -c "from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; print('ok')"`
Expected: prints `ok`, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock requirements.txt
git commit -m "chore: add langgraph-checkpoint-postgres, drop stale redis-checkpoint reference"
```

---

### Task 3: One-off checkpointer table setup script

**Files:**
- Create: `scripts/setup_checkpointer.py`

**Interfaces:**
- Consumes: `infra.postgres._get_psycopg_dsn() -> str` (Task 1). `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` (Task 2).

This mirrors the existing `scripts/create_user.py` pattern: a small, standalone, manually-run CLI script, not wired into app startup.

- [ ] **Step 1: Write the script**

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

- [ ] **Step 2: Run it against the real database**

Run: `uv run python -m scripts.setup_checkpointer`
Expected: prints `Checkpointer tables ready.`, exit code 0, no traceback. (`.setup()` is idempotent — safe to run again if needed.)

- [ ] **Step 3: Verify the tables exist**

Run:
```bash
uv run python -c "
import asyncio
from dotenv import load_dotenv
load_dotenv()
from infra.postgres import get_engine
from sqlalchemy import text

async def main():
    async with get_engine().begin() as conn:
        result = await conn.execute(text(
            \"SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'checkpoint%' ORDER BY table_name\"
        ))
        print([r[0] for r in result.fetchall()])

asyncio.run(main())
"
```
Expected: a list including `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` (and possibly `checkpoint_migrations`).

- [ ] **Step 4: Commit**

```bash
git add scripts/setup_checkpointer.py
git commit -m "feat: add one-off setup script for the Postgres checkpointer tables"
```

---

### Task 4: Wire the checkpointer into `api/main.py`'s lifespan

**Files:**
- Modify: `api/main.py`
- Modify: `agent/graph.py:52` (stale comment fix)

**Interfaces:**
- Consumes: `infra.postgres._get_psycopg_dsn() -> str` (Task 1), `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` (Task 2), `agent.graph.build_graph(checkpointer=None)` (existing, unchanged signature).

`build_graph`'s signature does not change — it already accepts an optional `checkpointer` and defaults to `MemorySaver()` when none is given, which is exactly why existing tests that call `build_graph()` with no arguments (e.g. `TestGraph::test_graph_compiles`, `TestGraph::test_graph_has_nodes` — currently pre-existing-failing for unrelated reasons, see Global Constraints in the design spec) are unaffected by this task.

- [ ] **Step 1: Fix the stale comment in `agent/graph.py`**

In `agent/graph.py`, change line 52 from:

```python
compiled_graph = None  # initialized in api/main.py lifespan with Redis checkpointer
```

to:

```python
compiled_graph = None  # initialized in api/main.py lifespan with a Postgres checkpointer
```

- [ ] **Step 2: Update `api/main.py`'s lifespan**

In `api/main.py`, change:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    import agent.graph as agent_graph
    from agent.graph import build_graph
    from infra.redis_client import get_redis, close_redis

    app.state.redis = await get_redis()
    agent_graph.compiled_graph = build_graph()

    yield
    await close_redis()
```

to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from contextlib import AsyncExitStack
    import agent.graph as agent_graph
    from agent.graph import build_graph
    from infra.redis_client import get_redis, close_redis
    from infra.postgres import _get_psycopg_dsn
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    app.state.redis = await get_redis()

    async with AsyncExitStack() as stack:
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(_get_psycopg_dsn())
        )
        agent_graph.compiled_graph = build_graph(checkpointer=checkpointer)
        yield

    await close_redis()
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `uv run python -c "from api.main import app; print('ok')"`
Expected: prints `ok`, exit code 0. (This only checks that the module's top-level code — route registration, etc. — is valid; the `lifespan` function body only runs when the app actually starts, which Task 5 covers.)

- [ ] **Step 4: Run the existing graph tests to confirm no regression**

Run: `uv run pytest tests/test_koda.py -k "TestGraph or TestRouterRegistration" -v`
Expected: same 4 pre-existing failures as before this task (`test_graph_compiles`, `test_graph_has_nodes`, `test_app_has_project_routes`, `test_app_has_chat_routes`) — unrelated to this change, not introduced or fixed by it. No *new* failures.

- [ ] **Step 5: Commit**

```bash
git add api/main.py agent/graph.py
git commit -m "feat: wire Postgres checkpointer into app lifespan"
```

---

### Task 5: Manual end-to-end verification

**Files:**
- None (verification only — no code changes expected).

**Interfaces:**
- None.

This proves the whole feature works together: a real server, a real chat message, a real restart, and confirmation the message history survives it. It requires `ANTHROPIC_KEY` set in `.env` (a real LLM call happens) and Redis reachable (the existing `_run_chat` background task still uses Redis for task-status polling, unrelated to this change, but the server won't serve requests without it). Both are already expected to be available per `TESTING.md`'s "Level 3 — Full stack" section, which this task follows.

If your environment cannot reach Docker/network for Redis, or has no `ANTHROPIC_KEY`, **stop and report BLOCKED with specifics** rather than skipping this task silently — this is the only task that proves the feature works end-to-end, so a genuine environment limitation needs to be flagged to the controller, not quietly passed over.

- [ ] **Step 1: Start Redis** (skip if already running — check with `redis-cli ping` first, expect `PONG`)

Run: `docker run -d --rm -p 6379:6379 --name koda-checkpointer-test redis:7-alpine`

- [ ] **Step 2: Start the API server in the background**

Run: `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &`
Wait ~2 seconds, then confirm: `curl -s http://localhost:8000/health` → expect `{"status":"ok"}`.

- [ ] **Step 3: Log in and create a chat**

```bash
COOKIE_JAR=/tmp/koda-checkpointer-test-cookies.txt
curl -s -c "$COOKIE_JAR" -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "sauravkumar585@gmail.com", "password": "sk@123456"}'
```
Expected: JSON with `user_id` and `email`, and `$COOKIE_JAR` now contains a `koda_session` cookie.

```bash
curl -s -b "$COOKIE_JAR" -X POST http://localhost:8000/api/v1/chats
```
Expected: JSON with a `chat_id`. Save it: `CHAT_ID=<the chat_id from the response>`.

- [ ] **Step 4: Send one short message and wait for it to complete**

```bash
curl -s -b "$COOKIE_JAR" -X POST "http://localhost:8000/api/v1/chats/$CHAT_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{"message": "Say the single word: pong"}'
```
Expected: JSON with a `task_id`. Save it: `TASK_ID=<the task_id from the response>`.

```bash
curl -s "http://localhost:8000/api/v1/status/$TASK_ID"
```
Poll this every couple seconds until `"status": "success"` (should take a few seconds — one short LLM call).

- [ ] **Step 5: Confirm the message shows up before restart**

```bash
curl -s -b "$COOKIE_JAR" "http://localhost:8000/api/v1/chats/$CHAT_ID"
```
Expected: JSON with `"messages"` containing at least the user's "Say the single word: pong" message and an assistant reply.

- [ ] **Step 6: Restart the server**

```bash
kill %1  # stops the backgrounded uvicorn from Step 2
```
Wait for it to exit, then repeat Step 2 exactly (start uvicorn again, confirm `/health`).

- [ ] **Step 7: Confirm the message still shows up after restart**

```bash
curl -s -b "$COOKIE_JAR" "http://localhost:8000/api/v1/chats/$CHAT_ID"
```
Expected: **identical** `"messages"` content as Step 5 — this is the actual proof persistence works, since before this plan's changes this response would have come back with `"messages": []` after a restart (the in-memory `MemorySaver` would have lost all state).

- [ ] **Step 8: Clean up**

```bash
kill %1  # stop uvicorn
docker stop koda-checkpointer-test  # stop the test Redis container (auto-removes, --rm)
rm -f /tmp/koda-checkpointer-test-cookies.txt
```

- [ ] **Step 9: Report the result**

No commit for this task (no code changes). In your task report, include the exact `messages` JSON from Step 5 and Step 7 side by side as evidence they match.
