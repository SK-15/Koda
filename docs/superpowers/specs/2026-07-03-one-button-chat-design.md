# One-Button New Chat — Design Spec

**Date:** 2026-07-03
**Status:** Proposed
**Project rule:** The agent guides; the user writes the implementation code.

## Goal

Kill the friction in starting a chat. Land on the page → composer is ready to
type, zero clicks. "New Chat" is one button, no forms, no project step.
Matches ChatGPT/Claude-style UX.

## Problem (current state)

Two disconnected paths exist today:

- **REST path** (what the frontend uses): `POST /projects` → `POST
  /projects/{id}/chats` → only then can `POST /chats/{id}/messages` succeed.
  First-time users are blocked by a forced "create project" form
  (`App.vue:55-56`, `326-338`) before they can even pick "new chat"
  (`App.vue:303-323`).
- **WS path** (`/api/v1/ws/run`): already frictionless — a `hello` frame with
  no `thread_id` auto-mints one server-side (`ws.py:211`). But nothing is
  written to Postgres, so WS-originated chats don't show up in
  `GET /projects/{id}/chats` history.

Root cause: **Project is a mandatory precursor to Chat**, and the frontend
forces the user through project creation/selection UI before unlocking the
composer.

## Decision

Keep Projects as a backend concept (workspace_path needs to live somewhere),
but stop requiring the user to ever see or manage one. Auto-provision one
implicit **default project per org/user**, lazily, on first chat creation.
Collapse project+chat creation into a single new endpoint.

Projects UI is removed from the app entirely for now (no hidden
switcher) — can come back later as a separate feature if multi-workspace
support is needed.

## Backend changes

### 1. `infra/projects_repo.py` — add `get_or_create_default`

```python
async def get_or_create_default(session, org_id: str, user_id: str) -> Project:
    existing = await get_first_for_owner(session, org_id, user_id)  # existing list query, LIMIT 1
    if existing:
        return existing
    return await create_project(
        session,
        org_id=org_id,
        user_id=user_id,
        name="Default",
        workspace_path=settings.DEFAULT_WORKSPACE_PATH,
    )
```

Reuses the existing `create_project` you already have in this file
(`projects_repo.py:7-24`) — just wraps it with a "does one already exist"
check scoped by org/user.

### 2. New config value

Add `DEFAULT_WORKSPACE_PATH` to wherever settings/env config lives today
(check `api/config.py` or equivalent — same place other env-driven values
are read). Default to something sane like `os.getcwd()` or an explicit env
var `KODA_DEFAULT_WORKSPACE`.

### 3. New route: `POST /api/v1/chats` (top-level, no `project_id` in path)

Add to `api/routes/chats.py`, alongside the existing nested route (don't
delete the nested one — keep it for later multi-project work, just unused by
the frontend now):

```python
@router.post("/chats")
async def create_chat_default(identity: Identity = Depends(get_identity), session=Depends(get_session)):
    org_id, user_id = identity
    project = await projects_repo.get_or_create_default(session, org_id, user_id)
    chat = await chats_repo.create_chat(session, project_id=project.project_id, org_id=org_id, user_id=user_id)
    return {"chat_id": chat.thread_id, "project_id": project.project_id, "title": None, "created_at": chat.created_at}
```

Match the exact signature/style of the existing
`POST /projects/{project_id}/chats` handler (`chats.py:50-67`) — same
dependencies, same response shape, just resolves the project internally
instead of taking it from the URL.

### 4. Nothing else changes

`POST /chats/{chat_id}/messages`, `GET /chats/{chat_id}`, the WS path, and
`/resume` are untouched. This is additive.

## Frontend changes (`koda-app`)

### 1. Delete the forced project gate

Remove `showProjectForm` state and the form markup (`App.vue:39-41`,
`326-338`), and the `loadProjects`/`selectProject` machinery
(`App.vue:50-107`) from the primary flow. Projects concept disappears from
the UI entirely.

### 2. Add `api.createChatDefault()` to `api.ts`

Same shape as the existing `createChat()` (`api.ts:57-59`) but hits
`POST /api/v1/chats` with no project id in the path.

### 3. Auto-create a chat on mount

Replace the `onMounted(loadProjects)` call (`App.vue:50`) with a call to
`api.createChatDefault()`, store the returned `chat_id` into
`currentChatId`, clear `messages`/`files`. Composer unlocks the instant this
resolves — no clicks needed.

### 4. "+ New Chat" button

Keep the button (`App.vue:323`), but simplify `newChat()`
(`App.vue:130-145`) to just call `api.createChatDefault()` (no
`currentProjectId` check needed anymore — always succeeds) and reset chat
state the same way as step 3.

### 5. Chat history / switching between past chats

Out of scope for this spec. Today's `GET /projects/{id}/chats` /
`selectChat()` machinery can stay as dead code for now or be wired to a
`GET /api/v1/chats` (all-chats-for-user) endpoint later if a sidebar history
list is wanted — separate follow-up.

## Out of scope

- Multi-project / project switcher UI.
- Chat history sidebar (listing past chats) — current spec only fixes chat
  *creation* friction.
- Bridging WS-path threads into Postgres (still two paths; frontend keeps
  using REST-created chat_id + WS for the actual message send, exactly as
  today).
- Auth.

## File touch list

| File | Change |
|---|---|
| `koda/infra/projects_repo.py` | add `get_or_create_default` |
| `koda/api/config.py` (or wherever settings live) | add `DEFAULT_WORKSPACE_PATH` |
| `koda/api/routes/chats.py` | add `POST /chats` route |
| `koda-app/src/api.ts` | add `createChatDefault()` |
| `koda-app/src/App.vue` | remove project form/gate, auto-create chat on mount, simplify `newChat()` |
