# Chat API — Design Spec

**Date:** 2026-06-24
**Status:** Approved (design)
**Project rule:** The agent guides; the user writes the implementation code.

## Goal

Add a Projects + Chats API so a UI can let users manage multiple projects (each
tied to one workspace) and hold multiple multi-turn conversations per project.
Chats are first-class persistent resources; each chat is a LangGraph thread.

## Decisions

- **Identity:** `X-Org-Id` / `X-User-Id` headers, defaulting to `"default"`. No JWT auth for now.
- **Message history:** Option A — read-append-invoke. No reducer change to `AgentState`. Message continuation logic lives entirely in the chats route/service.
- **Persistence model:** Hybrid (option 3). Postgres holds the index (project list, chat list, last_message, title, cost, timestamps). Full transcript comes from the LangGraph checkpointer on demand.
- **chat_id == thread_id.** No separate id.
- **workspace_path** comes from the project, not from the chat/message request.
- **Old `/run` endpoint** kept as-is until a UI migrates away from it.

## Database

Tables already created in Neon. SQLAlchemy models must be updated to match.

```sql
-- already run in Neon:

CREATE TABLE IF NOT EXISTS projects (
    project_id     TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    name           TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT now(),
    updated_at     TIMESTAMP NOT NULL DEFAULT now()
);

ALTER TABLE threads ADD COLUMN IF NOT EXISTS project_id TEXT;
ALTER TABLE threads ADD COLUMN IF NOT EXISTS title      TEXT;

ALTER TABLE threads
    ADD CONSTRAINT fk_threads_project
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
    ON DELETE CASCADE;
```

## SQLAlchemy models (`koda/infra/postgres.py`)

**New `Project` class:**
```python
class Project(Base):
    __tablename__ = "projects"
    project_id     = Column(String, primary_key=True)
    org_id         = Column(String, nullable=False)
    user_id        = Column(String, nullable=False)
    name           = Column(String, nullable=False)
    workspace_path = Column(String, nullable=False)
    created_at     = Column(DateTime, server_default=func.now())
    updated_at     = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

**Extended `ThreadRecord`** (add two columns):
```python
    project_id = Column(String, nullable=True)   # FK -> projects.project_id
    title      = Column(String, nullable=True)   # derived from first user message
```

## Endpoints

All under `/api/v1`. Org/user from `X-Org-Id` / `X-User-Id` headers (default `"default"`).

### Projects

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/projects` | `{name, workspace_path}` | `{project_id, name, workspace_path, created_at}` |
| GET | `/projects` | — | `[{project_id, name, workspace_path, created_at}]` (owner-scoped) |
| GET | `/projects/{project_id}` | — | project row + `chat_count` |

Ownership filter on every query: `WHERE org_id=.. AND user_id=..`. Returns 404 for not-found AND not-owned (don't leak existence).

### Chats

| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/projects/{project_id}/chats` | `{title?}` | `{chat_id, project_id, title}` |
| GET | `/projects/{project_id}/chats` | — | `[{chat_id, title, last_message, updated_at, cost_usd}]` |
| GET | `/chats/{chat_id}` | — | `{chat_id, title, messages: [{role, content}]}` |
| POST | `/chats/{chat_id}/messages` | `{message, plan_mode?, budget_limit_usd?, max_iterations?, model?}` | `{chat_id, task_id, status}` |

`GET /chats/{chat_id}` fetches the transcript from the LangGraph checkpointer
(`aget_state`) and serializes `messages` into `[{role, content}]`.

`POST /chats/{chat_id}/messages` is the multi-turn entry point — see section below.

**Existing `/resume/{thread_id}`** unchanged. Works for both plan-approval and
tool-approval. No change needed.

## Multi-turn message flow (Option A)

Logic lives in the `POST /chats/{chat_id}/messages` handler:

```python
config = {"configurable": {"thread_id": chat_id}}
snapshot = await graph.aget_state(config)
is_first_turn = not snapshot or not snapshot.values.get("messages")

if is_first_turn:
    # seed full initial state (workspace from project row)
    invoke_input = {
        "messages": [HumanMessage(content=body.message)],
        "summary": "",
        "iterations": 0,
        "max_iterations": body.max_iterations,
        "tool_attempts": {},
        "last_error": None,
        "approved": None,
        "awaiting_approval": False,
        "plan": None,
        "plan_approved": None,
        "plan_mode": body.plan_mode,
        "current_step": 0,
        "memory_index": "",
        "workspace_path": project.workspace_path,   # from project row
        "org_id": org_id,
        "user_id": user_id,
        "thread_id": chat_id,
        "tokens_used": 0,
        "cost_usd": 0.0,
        "budget_limit_usd": body.budget_limit_usd,
        "model": body.model,
    }
else:
    # append to existing thread — reset only per-turn fields
    prior = snapshot.values.get("messages", [])
    invoke_input = {
        "messages": prior + [HumanMessage(content=body.message)],
        "iterations": 0,
        "last_error": None,
        "plan": None,
        "plan_approved": None,
        "plan_mode": body.plan_mode,
        "current_step": 0,
        "approved": None,
        "awaiting_approval": False,
        "budget_limit_usd": body.budget_limit_usd,
        "max_iterations": body.max_iterations,
        "model": body.model,
    }
```

After queuing the background task:
- Write `threads.last_message = body.message[:500]` (for chat list view).
- If `threads.title IS NULL`, set `title = body.message[:80]` (first message becomes title).

## Serializer (`koda/api/serializers.py`)

Converts LangChain message objects to `{role, content}` for the transcript endpoint:

```python
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

def serialize_messages(messages: list) -> list[dict]:
    role_map = {
        HumanMessage: "user",
        AIMessage: "assistant",
        SystemMessage: "system",
        ToolMessage: "tool",
    }
    result = []
    for m in messages:
        role = role_map.get(type(m), "unknown")
        content = m.content if isinstance(m.content, str) else str(m.content)
        result.append({"role": role, "content": content})
    return result
```

## Identity dependency (`koda/api/deps.py`)

```python
from fastapi import Header

async def get_identity(
    x_org_id: str = Header(default="default"),
    x_user_id: str = Header(default="default"),
) -> tuple[str, str]:
    return x_org_id, x_user_id
```

Used as a FastAPI `Depends` on every projects/chats route.

## Error handling

- `404` — project not found or not owned; chat not found or not owned (same response, don't leak).
- `400` — empty `name`, empty `workspace_path`, empty `message`.
- If project deleted (FK cascade removes threads), chat lookup returns 404.
- Budget/iteration guards enforced inside the graph per turn (unchanged).

## File layout

| File | Status | Responsibility |
|------|--------|---------------|
| `koda/infra/postgres.py` | Modify | Add `Project` model, extend `ThreadRecord` |
| `koda/infra/projects_repo.py` | Create | Project DB ops (create, get, list) |
| `koda/infra/chats_repo.py` | Create | Chat DB ops (create, list, get, update last_message/title) |
| `koda/api/deps.py` | Create | `get_identity()` FastAPI dependency |
| `koda/api/serializers.py` | Create | `serialize_messages()` |
| `koda/api/routes/projects.py` | Create | Project endpoints |
| `koda/api/routes/chats.py` | Create | Chat endpoints + message continuation |
| `koda/api/main.py` | Modify | Register new routers |
| `koda/tests/test_koda.py` | Modify | Tests for all new units |

## Testing

Unit tests only (match existing style — pytest classes, no real Neon). Approach:
- **Request model tests** — Pydantic defaults/validation for `CreateProjectRequest`, `SendMessageRequest`.
- **Repo tests** — monkeypatch the DB session; assert correct SQL filters, id generation, `last_message`/`title` writes.
- **Message-continuation logic** — unit test the read-append helper directly: given a fake snapshot with prior messages, assert `invoke_input["messages"] == prior + [new]` and per-turn fields reset correctly.
- **Serializer tests** — `serialize_messages()` maps all four message types to correct roles.

## Out of scope (this spec)

- JWT auth (deferred — explicit ids for now).
- Option B (`add_messages` reducer on `AgentState`) — later refactor.
- Streaming/SSE — status still polled via existing `/status/{task_id}`.
- Project deletion endpoint — not needed yet.
- Chat deletion endpoint — not needed yet.
- Alembic migrations — schema applied directly in Neon via SQL.
