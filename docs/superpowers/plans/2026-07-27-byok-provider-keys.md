# BYOK Provider Keys Implementation Plan

> **Execution mode for this plan:** koda has a standing pairing rule — the
> user writes koda's source themselves; Claude coaches (points to exact
> files/lines, reviews the result, doesn't Edit/Write source files). This
> plan is written for that mode: each task is something *you* type and
> run, with Claude reviewing between tasks — not something Claude executes
> unattended. (The standard "Subagent-Driven" / "Inline Execution" handoff
> at the end of the writing-plans skill assumes Claude executes; that
> doesn't apply here, so skip it.)

**Goal:** Let a koda user configure their own API key — for a built-in
provider or an arbitrary OpenAI-compatible endpoint — so their usage
bills to their own account instead of the operator's `models.yaml` key,
falling back to the operator's key when the user hasn't configured one.

**Architecture:** A new `user_provider_keys` table stores one row per
`(user_id, alias)`, holding a Fernet-encrypted API key and an optional
`base_url`. `llm/router.py`'s model resolution becomes async (it now
needs a DB round trip) and checks this table before falling back to
`models.yaml`. Three new REST routes manage the rows. The `"provider/model"`
string convention becomes `"alias/model"` — a superset, since every
built-in provider name is already a valid alias with zero rows.

**Tech Stack:** SQLAlchemy async ORM (existing), `cryptography` (Fernet,
new direct dependency, already present transitively via `pyjwt`), FastAPI
routes (existing pattern), pytest + pytest-asyncio (existing).

## Global Constraints

- Spec source of truth: `docs/superpowers/specs/2026-07-27-byok-provider-keys-design.md`.
- `provider_kind` must be one of: `anthropic`, `openai`, `gemini`,
  `deepseek`, `ollama`, `openai_compatible`.
- `openai_compatible` requires `base_url`; the other five don't.
- A user's own key always wins over the operator's `models.yaml` key for
  the same alias; if neither exists, raise `ValueError` with the exact
  message `"No key configured for '{alias}'. Add one via POST /provider-keys or use a built-in provider."`.
- Decrypted key material must never be logged, returned in an API
  response, or persisted outside `api_key_encrypted`.
- New env var: `KEY_ENCRYPTION_SECRET` (a Fernet-compatible base64 32-byte
  key). Missing it must raise `RuntimeError`, not silently no-op.

## Note on a ripple this plan found

The spec's resolution step needs a DB read. `llm/router.py`'s
`_build_base_llm`/`get_llm`/`get_planner_llm` are currently synchronous
functions, even though every caller is an `async def` graph node. Making
the resolution work means these three functions become `async def`, and
every call site (production and test) that calls them needs an `await` /
async-compatible mock. Task 5 and Task 6 cover this exactly — it's
mechanical but touches more files than the spec's own file table lists
(`agent/nodes/planner_node.py`, `agent/nodes/summarize_node.py`,
`tools/vision_describe_tool.py`, and several existing tests in
`tests/test_koda.py` and `tests/test_vision_describe_tool.py`). This is a
compatible refinement of the spec, not a scope change — the spec's public
interfaces (`resolve_user_key`, route shapes, table schema) are
unaffected.

---

### Task 1: Encryption helper + dependency + env var

**Files:**
- Create: `infra/crypto.py`
- Modify: `pyproject.toml` (add `cryptography` as a direct dependency)
- Modify: `requirements.txt` (same)
- Modify: `.env.example` (add `KEY_ENCRYPTION_SECRET`)
- Test: `tests/test_provider_keys.py` (new file)

**Interfaces:**
- Produces: `infra.crypto.encrypt_key(plaintext: str) -> str`,
  `infra.crypto.decrypt_key(token: str) -> str`. Task 5 and Task 7 both
  import these.

- [ ] **Step 1: Add `cryptography` as a direct dependency**

In `pyproject.toml`, find this block (it's the last item before the
`[project.optional-dependencies]` table):

```toml
    # MCP client
    "mcp>=1.0.0",
]
```

Change it to:

```toml
    # MCP client
    "mcp>=1.0.0",

    # Key encryption (BYOK provider keys)
    "cryptography>=42.0.0",
]
```

In `requirements.txt`, find:

```
# Search
tavily-python>=0.7.0
```

Change it to:

```
# Search
tavily-python>=0.7.0

# Key encryption (BYOK provider keys)
cryptography>=42.0.0
```

Then run:

```bash
uv sync
```

Expected: resolves cleanly — `cryptography` is already installed
transitively (via `pyjwt`), so this should just promote it to a direct
dependency without downloading anything new.

- [ ] **Step 2: Add `KEY_ENCRYPTION_SECRET` to `.env.example`**

At the end of `.env.example`, add:

```
# Key encryption (BYOK provider keys)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
KEY_ENCRYPTION_SECRET=
```

- [ ] **Step 3: Write the failing tests for `infra/crypto.py`**

Create `tests/test_provider_keys.py` with this content:

```python
import pytest


class TestCrypto:
    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        from cryptography.fernet import Fernet
        monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())

        from infra.crypto import encrypt_key, decrypt_key
        encrypted = encrypt_key("sk-super-secret")
        assert encrypted != "sk-super-secret"
        assert decrypt_key(encrypted) == "sk-super-secret"

    def test_encrypt_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("KEY_ENCRYPTION_SECRET", raising=False)

        from infra.crypto import encrypt_key
        with pytest.raises(RuntimeError):
            encrypt_key("sk-super-secret")
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'infra.crypto'`

- [ ] **Step 5: Write `infra/crypto.py`**

```python
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    secret = os.getenv("KEY_ENCRYPTION_SECRET")
    if not secret:
        raise RuntimeError("KEY_ENCRYPTION_SECRET not set. Add it to .env")
    return Fernet(secret.encode())


def encrypt_key(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_key(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add infra/crypto.py pyproject.toml requirements.txt uv.lock .env.example tests/test_provider_keys.py
git commit -m "feat: add Fernet-based key encryption helper for BYOK"
```

---

### Task 2: `UserProviderKey` ORM model

**Files:**
- Modify: `infra/postgres.py`
- Test: `tests/test_koda.py` (`TestOrmModels` class, line ~448)

**Interfaces:**
- Consumes: nothing new.
- Produces: `infra.postgres.UserProviderKey` — columns `id`, `user_id`,
  `alias`, `provider_kind`, `api_key_encrypted`, `base_url`, `created_at`.
  Task 3's repo module imports this.

- [ ] **Step 1: Write the failing test**

In `tests/test_koda.py`, inside the existing `TestOrmModels` class
(starts at line 448), add a new method after `test_user_model_has_fields`:

```python
    def test_user_provider_key_model_has_fields(self):
        from infra.postgres import UserProviderKey
        cols = {c.name for c in UserProviderKey.__table__.columns}
        assert cols >= {
            "id", "user_id", "alias", "provider_kind",
            "api_key_encrypted", "base_url", "created_at",
        }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_koda.py::TestOrmModels::test_user_provider_key_model_has_fields -v`
Expected: FAIL with `ImportError: cannot import name 'UserProviderKey'`

- [ ] **Step 3: Add the model to `infra/postgres.py`**

First, update the sqlalchemy import line near the top of the file (it
currently reads):

```python
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, func
```

Change it to:

```python
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, func, UniqueConstraint
```

Then, directly after the `ThreadRecord` class (right before
`def _get_db_url():`), add:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_koda.py::TestOrmModels -v`
Expected: 4 passed (the 3 existing `TestOrmModels` tests plus the new one)

- [ ] **Step 5: Commit**

```bash
git add infra/postgres.py tests/test_koda.py
git commit -m "feat: add UserProviderKey table for BYOK provider keys"
```

---

### Task 3: Provider-keys repository (DB CRUD)

**Files:**
- Create: `infra/provider_keys_repo.py`
- Test: `tests/test_provider_keys.py` (extend from Task 1)

**Interfaces:**
- Consumes: `infra.postgres.UserProviderKey` (Task 2).
- Produces:
  - `create_or_update(db, user_id: str, alias: str, provider_kind: str, api_key_encrypted: str, base_url: str | None = None) -> UserProviderKey`
  - `get_by_alias(db, user_id: str, alias: str) -> UserProviderKey | None`
  - `list_for_user(db, user_id: str) -> list[UserProviderKey]`
  - `delete_by_alias(db, user_id: str, alias: str) -> bool`

  Task 4 (`llm/user_keys.py`) uses `get_by_alias`. Task 7 (routes) uses
  all four.

- [ ] **Step 1: Write the failing tests**

Append this to `tests/test_provider_keys.py` (after the `TestCrypto`
class):

```python
class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeSession:
    def __init__(self, execute_results=None):
        self._execute_results = list(execute_results or [])
        self.added = []
        self.deleted = []
        self.committed = False
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def execute(self, *_args, **_kwargs):
        return self._execute_results.pop(0)


class TestProviderKeysRepo:
    @pytest.mark.asyncio
    async def test_get_by_alias_none_when_not_found(self):
        from infra import provider_keys_repo

        session = _FakeSession(execute_results=[_FakeResult(None)])
        result = await provider_keys_repo.get_by_alias(session, "user-1", "anthropic")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_alias_returns_row(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        row = UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="enc")
        session = _FakeSession(execute_results=[_FakeResult(row)])
        result = await provider_keys_repo.get_by_alias(session, "user-1", "anthropic")
        assert result is row

    @pytest.mark.asyncio
    async def test_create_or_update_creates_new_row(self):
        from infra import provider_keys_repo

        session = _FakeSession(execute_results=[_FakeResult(None)])
        result = await provider_keys_repo.create_or_update(
            session, "user-1", "anthropic", "anthropic", "enc-key", None,
        )
        assert result.user_id == "user-1"
        assert result.alias == "anthropic"
        assert result.provider_kind == "anthropic"
        assert result.api_key_encrypted == "enc-key"
        assert result.id is not None
        assert session.added == [result]
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_create_or_update_updates_existing_row(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        existing = UserProviderKey(
            id="id-1", user_id="user-1", alias="anthropic",
            provider_kind="anthropic", api_key_encrypted="old-enc", base_url=None,
        )
        session = _FakeSession(execute_results=[_FakeResult(existing)])
        result = await provider_keys_repo.create_or_update(
            session, "user-1", "anthropic", "anthropic", "new-enc", None,
        )
        assert result is existing
        assert result.api_key_encrypted == "new-enc"
        assert session.added == []
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_list_for_user_returns_rows(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        rows = [
            UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="e1"),
            UserProviderKey(id="id-2", user_id="user-1", alias="openrouter", provider_kind="openai_compatible", api_key_encrypted="e2", base_url="https://openrouter.ai/api/v1"),
        ]
        session = _FakeSession(execute_results=[_FakeResult(rows)])
        result = await provider_keys_repo.list_for_user(session, "user-1")
        assert result == rows

    @pytest.mark.asyncio
    async def test_delete_by_alias_returns_false_when_missing(self):
        from infra import provider_keys_repo

        session = _FakeSession(execute_results=[_FakeResult(None)])
        result = await provider_keys_repo.delete_by_alias(session, "user-1", "anthropic")
        assert result is False
        assert session.deleted == []

    @pytest.mark.asyncio
    async def test_delete_by_alias_deletes_and_returns_true(self):
        from infra import provider_keys_repo
        from infra.postgres import UserProviderKey

        row = UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="e1")
        session = _FakeSession(execute_results=[_FakeResult(row)])
        result = await provider_keys_repo.delete_by_alias(session, "user-1", "anthropic")
        assert result is True
        assert session.deleted == [row]
        assert session.committed is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py::TestProviderKeysRepo -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'infra.provider_keys_repo'`

- [ ] **Step 3: Write `infra/provider_keys_repo.py`**

```python
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres import UserProviderKey


async def get_by_alias(db: AsyncSession, user_id: str, alias: str) -> UserProviderKey | None:
    result = await db.execute(
        select(UserProviderKey).where(
            UserProviderKey.user_id == user_id,
            UserProviderKey.alias == alias,
        )
    )
    return result.scalar_one_or_none()


async def create_or_update(
    db: AsyncSession,
    user_id: str,
    alias: str,
    provider_kind: str,
    api_key_encrypted: str,
    base_url: str | None = None,
) -> UserProviderKey:
    existing = await get_by_alias(db, user_id, alias)
    if existing is not None:
        existing.provider_kind = provider_kind
        existing.api_key_encrypted = api_key_encrypted
        existing.base_url = base_url
        await db.commit()
        await db.refresh(existing)
        return existing

    row = UserProviderKey(
        id=str(uuid.uuid4()),
        user_id=user_id,
        alias=alias,
        provider_kind=provider_kind,
        api_key_encrypted=api_key_encrypted,
        base_url=base_url,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_for_user(db: AsyncSession, user_id: str) -> list[UserProviderKey]:
    result = await db.execute(
        select(UserProviderKey)
        .where(UserProviderKey.user_id == user_id)
        .order_by(UserProviderKey.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_by_alias(db: AsyncSession, user_id: str, alias: str) -> bool:
    existing = await get_by_alias(db, user_id, alias)
    if existing is None:
        return False
    await db.delete(existing)
    await db.commit()
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py -v`
Expected: 9 passed (2 from Task 1's `TestCrypto` + 7 from `TestProviderKeysRepo`)

- [ ] **Step 5: Commit**

```bash
git add infra/provider_keys_repo.py tests/test_provider_keys.py
git commit -m "feat: add provider_keys_repo CRUD for BYOK"
```

---

### Task 4: `resolve_user_key` lookup

**Files:**
- Create: `llm/user_keys.py`
- Test: `tests/test_provider_keys.py`

**Interfaces:**
- Consumes: `infra.provider_keys_repo.get_by_alias` (Task 3),
  `infra.postgres.get_session_factory` (existing).
- Produces: `async resolve_user_key(user_id: str | None, alias: str) -> UserProviderKey | None`.
  Task 5 (`llm/router.py`) awaits this directly — no `db` parameter is
  threaded in, it opens its own session, matching the self-contained
  pattern `llm/cost_tracker.py:record_usage` already uses (`async with
  get_session_factory()() as session:`), since `_build_base_llm` has no
  request-scoped session available to it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_provider_keys.py`:

```python
class TestResolveUserKey:
    @pytest.mark.asyncio
    async def test_returns_none_when_user_id_is_none(self):
        from llm.user_keys import resolve_user_key
        result = await resolve_user_key(None, "anthropic")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_row_from_repo(self, monkeypatch):
        import llm.user_keys as uk
        from infra.postgres import UserProviderKey
        from unittest.mock import AsyncMock

        row = UserProviderKey(id="id-1", user_id="user-1", alias="anthropic", provider_kind="anthropic", api_key_encrypted="enc")

        class _FakeSessionCtx:
            async def __aenter__(self):
                return "fake-session"

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(uk, "get_session_factory", lambda: (lambda: _FakeSessionCtx()))
        monkeypatch.setattr(uk.provider_keys_repo, "get_by_alias", AsyncMock(return_value=row))

        result = await uk.resolve_user_key("user-1", "anthropic")
        assert result is row
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py::TestResolveUserKey -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm.user_keys'`

- [ ] **Step 3: Write `llm/user_keys.py`**

```python
from infra.postgres import get_session_factory
from infra import provider_keys_repo


async def resolve_user_key(user_id: str | None, alias: str):
    if not user_id:
        return None
    async with get_session_factory()() as session:
        return await provider_keys_repo.get_by_alias(session, user_id, alias)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add llm/user_keys.py tests/test_provider_keys.py
git commit -m "feat: add resolve_user_key lookup for BYOK"
```

---

### Task 5: Wire BYOK into `llm/router.py` (becomes async)

**Files:**
- Modify: `llm/router.py`
- Test: `tests/test_provider_keys.py`
- Test: `tests/test_koda.py` (`TestPlanSchema.test_router_exposes_planner_builder`, line ~287 — verify it still passes, no change needed)

**Interfaces:**
- Consumes: `llm.user_keys.resolve_user_key` (Task 4),
  `infra.crypto.decrypt_key` (Task 1).
- Produces: `async def get_llm(model=None, enabled_tools=None, user_id=None)`,
  `async def _build_base_llm(model=None, user_id=None)`,
  `async def get_planner_llm(model=None)` — all three are now
  coroutines; every caller must `await` them. Task 6 updates every call
  site.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_provider_keys.py`:

```python
class TestBuildBaseLlmWithUserKeys:
    @pytest.mark.asyncio
    async def test_uses_user_key_when_present(self, monkeypatch):
        import llm.router as router
        from infra.postgres import UserProviderKey

        row = UserProviderKey(
            id="id-1", user_id="user-1", alias="anthropic",
            provider_kind="anthropic", api_key_encrypted="enc-key", base_url=None,
        )

        async def fake_resolve(user_id, alias):
            assert user_id == "user-1"
            assert alias == "anthropic"
            return row

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        monkeypatch.setattr(router, "decrypt_key", lambda token: "decrypted-" + token)

        captured = {}

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_anthropic
        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)

        result = await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id="user-1")
        assert captured["api_key"] == "decrypted-enc-key"

    @pytest.mark.asyncio
    async def test_falls_back_to_env_key_when_no_user_row(self, monkeypatch):
        import llm.router as router

        async def fake_resolve(user_id, alias):
            return None

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        # _get_config() memoizes into a module-global on first call, so real
        # env-var expansion is order-dependent across the test session —
        # patch the config directly instead of monkeypatch.setenv.
        monkeypatch.setattr(router, "_get_config", lambda: {
            "providers": {"anthropic": {"api_key": "env-key-value"}},
            "default_model": "anthropic/claude-sonnet-4-5",
        })

        captured = {}

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_anthropic
        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)

        result = await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id="user-1")
        assert captured["api_key"] == "env-key-value"

    @pytest.mark.asyncio
    async def test_openai_compatible_user_row_passes_base_url(self, monkeypatch):
        import llm.router as router
        from infra.postgres import UserProviderKey

        row = UserProviderKey(
            id="id-1", user_id="user-1", alias="openrouter",
            provider_kind="openai_compatible", api_key_encrypted="enc-key",
            base_url="https://openrouter.ai/api/v1",
        )

        async def fake_resolve(user_id, alias):
            return row

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        monkeypatch.setattr(router, "decrypt_key", lambda token: "decrypted-" + token)

        captured = {}

        class FakeChatOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_openai
        monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)

        result = await router._build_base_llm("openrouter/mixtral-8x7b", user_id="user-1")
        assert captured["api_key"] == "decrypted-enc-key"
        assert captured["base_url"] == "https://openrouter.ai/api/v1"

    @pytest.mark.asyncio
    async def test_unknown_alias_with_no_user_row_raises_documented_message(self, monkeypatch):
        import llm.router as router

        async def fake_resolve(user_id, alias):
            return None

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)

        with pytest.raises(ValueError, match="No key configured for 'openrouter'"):
            await router._build_base_llm("openrouter/mixtral-8x7b", user_id="user-1")

    @pytest.mark.asyncio
    async def test_decrypt_failure_raises_generic_value_error(self, monkeypatch):
        import llm.router as router
        from infra.postgres import UserProviderKey

        row = UserProviderKey(
            id="id-1", user_id="user-1", alias="anthropic",
            provider_kind="anthropic", api_key_encrypted="corrupted-token", base_url=None,
        )

        async def fake_resolve(user_id, alias):
            return row

        def fake_decrypt(token):
            raise ValueError("Fernet token is invalid")  # simulates cryptography.fernet.InvalidToken

        monkeypatch.setattr(router, "resolve_user_key", fake_resolve)
        monkeypatch.setattr(router, "decrypt_key", fake_decrypt)

        with pytest.raises(ValueError, match="Key store misconfigured"):
            await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id="user-1")

    @pytest.mark.asyncio
    async def test_no_user_id_falls_back_to_env_key(self, monkeypatch):
        # resolve_user_key itself guards on falsy user_id (Task 4's
        # test_returns_none_when_user_id_is_none covers that directly).
        # This test just confirms _build_base_llm's fallback path still
        # works end-to-end when user_id is None.
        import llm.router as router

        monkeypatch.setattr(router, "_get_config", lambda: {
            "providers": {"anthropic": {"api_key": "env-key-value"}},
            "default_model": "anthropic/claude-sonnet-4-5",
        })

        captured = {}

        class FakeChatAnthropic:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import langchain_anthropic
        monkeypatch.setattr(langchain_anthropic, "ChatAnthropic", FakeChatAnthropic)

        result = await router._build_base_llm("anthropic/claude-sonnet-4-5", user_id=None)
        assert captured["api_key"] == "env-key-value"
```

Note: these tests patch `langchain_anthropic.ChatAnthropic` /
`langchain_openai.ChatOpenAI` at their source module, not on `router`,
because Step 3 below imports them lazily inside `_build_client` (`from
langchain_anthropic import ChatAnthropic`) — patching the origin module
is what actually takes effect for a lazy `from x import y` done after the
patch.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py::TestBuildBaseLlmWithUserKeys -v`
Expected: FAIL — `router._build_base_llm` isn't a coroutine yet /
`resolve_user_key`, `decrypt_key`, `_build_client` don't exist as
attributes on `router` yet (`AttributeError`).

- [ ] **Step 3: Rewrite `llm/router.py`**

Full new contents:

```python
import os
from tools.registry import all_tools
from llm.model_config import load_model_config, get_litellm_params, get_default_model, get_fallback_model
from llm.user_keys import resolve_user_key
from infra.crypto import decrypt_key


_config = None


def _get_config() -> dict:
    global _config
    if _config is None:
        _config = load_model_config()
    return _config


def _get_tool_schemas(enabled_tools: list[str] | None = None) -> list:
    schemas = []
    for tool in all_tools():
        if enabled_tools is not None and tool.name not in enabled_tools:
            continue
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_class.model_json_schema(),
            }
        })
    return schemas


def _build_client(provider_kind: str, model_name: str, api_key: str | None, base_url: str | None = None):
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_ollama import ChatOllama

    # streaming=True lets even ainvoke emit on_chat_model_stream events, which
    # the WS layer forwards as token deltas. ainvoke still returns the full
    # aggregated message, so non-streaming (REST) callers are unaffected.
    if provider_kind == "anthropic":
        return ChatAnthropic(model=model_name, api_key=api_key, max_tokens=4096, streaming=True)
    elif provider_kind == "openai":
        return ChatOpenAI(model=model_name, api_key=api_key, streaming=True)
    elif provider_kind == "gemini":
        return ChatGoogleGenerativeAI(model=model_name, google_api_key=api_key)
    elif provider_kind == "ollama":
        return ChatOllama(model=model_name, base_url=base_url or "http://localhost:11434")
    elif provider_kind == "deepseek":
        return ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url or "https://api.deepseek.com/v1", streaming=True)
    elif provider_kind == "openai_compatible":
        return ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url, streaming=True)
    else:
        raise ValueError(f"Unsupported provider: {provider_kind}")


async def _build_base_llm(model: str = None, user_id: str = None):
    config = _get_config()
    model = model or get_default_model(config)

    if "/" not in model:
        raise ValueError(f"Model must be 'provider/model', got: {model}")

    alias, model_name = model.split("/", 1)

    user_key_row = await resolve_user_key(user_id, alias)
    if user_key_row is not None:
        try:
            api_key = decrypt_key(user_key_row.api_key_encrypted)
        except Exception:
            # Never leak the raw decrypt exception or key material — a
            # corrupted/rotated KEY_ENCRYPTION_SECRET is an operator problem,
            # not something the end user can act on.
            raise ValueError("Key store misconfigured — could not decrypt provider key. Contact the operator.")
        return _build_client(user_key_row.provider_kind, model_name, api_key, user_key_row.base_url)

    provider_config = config.get("providers", {}).get(alias)
    if provider_config is None:
        raise ValueError(
            f"No key configured for '{alias}'. Add one via POST /provider-keys or use a built-in provider."
        )

    params = get_litellm_params(model, config)
    return _build_client(alias, model_name, params.get("api_key"), params.get("api_base"))


async def get_llm(model: str = None, enabled_tools: list[str] | None = None, user_id: str = None):
    """Build the LLM bound to a session-scoped tool set.

    enabled_tools=None binds all registered tools (default / local runs).
    A capability-negotiated session passes the client-advertised subset; an
    empty list binds no tools, yielding a pure-chat agent.
    """
    schemas = _get_tool_schemas(enabled_tools)
    llm = await _build_base_llm(model, user_id)
    if not schemas:
        return llm
    return llm.bind_tools(schemas)


async def get_planner_llm(model: str = None):
    from agent.plan_schema import Plan
    llm = await _build_base_llm(model)
    return llm.with_structured_output(Plan)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py -v`
Expected: 17 passed (2 `TestCrypto` + 7 `TestProviderKeysRepo` + 2 `TestResolveUserKey` + 6 `TestBuildBaseLlmWithUserKeys`)

Then confirm the pre-existing router test still passes (it only checks
`hasattr`, so async-ness doesn't affect it):

Run: `.venv/bin/python -m pytest tests/test_koda.py::TestPlanSchema::test_router_exposes_planner_builder -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add llm/router.py tests/test_provider_keys.py
git commit -m "feat: resolve BYOK user keys in router, fall back to models.yaml"
```

Do **not** run the full test suite yet — Task 6 fixes the call sites and
existing test fakes that this change breaks. Running `pytest` on the
whole repo right now will show failures in `test_koda.py` and
`test_vision_describe_tool.py`; that's expected and fixed next.

---

### Task 6: Update every caller of the now-async router functions

**Files:**
- Modify: `agent/nodes/agent_node.py`
- Modify: `agent/nodes/planner_node.py`
- Modify: `agent/nodes/summarize_node.py`
- Modify: `tools/vision_describe_tool.py`
- Modify: `tests/test_koda.py` (7 call sites + 1 new test)
- Modify: `tests/test_vision_describe_tool.py` (3 call sites)

**Interfaces:**
- Consumes: `llm.router.get_llm`, `llm.router.get_planner_llm`,
  `llm.router._build_base_llm` (all async as of Task 5).
- Produces: no new interfaces — this task only makes existing call sites
  correct again.

- [ ] **Step 1: Fix `agent/nodes/agent_node.py`**

Find:

```python
    system_prompt = build_system_prompt(state)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    llm = get_llm(model=state.get("model"), enabled_tools=state.get("enabled_tools"))
    response = await llm.ainvoke(messages)
```

Replace with:

```python
    system_prompt = build_system_prompt(state)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    try:
        llm = await get_llm(
            model=state.get("model"),
            enabled_tools=state.get("enabled_tools"),
            user_id=state.get("user_id"),
        )
        response = await llm.ainvoke(messages)
    except ValueError as e:
        return {
            "iterations": iterations,
            "messages": state["messages"] + [AIMessage(content=str(e))],
        }
```

- [ ] **Step 2: Fix `agent/nodes/planner_node.py`**

Find:

```python
    llm = get_planner_llm(model=state.get("model"))
```

Replace with:

```python
    llm = await get_planner_llm(model=state.get("model"))
```

- [ ] **Step 3: Fix `agent/nodes/summarize_node.py`**

Find:

```python
    llm = get_llm()
```

Replace with:

```python
    llm = await get_llm()
```

- [ ] **Step 4: Fix `tools/vision_describe_tool.py`**

Find:

```python
        try:
            from llm.router import _build_base_llm
            llm = _build_base_llm(input.model)
```

Replace with:

```python
        try:
            from llm.router import _build_base_llm
            llm = await _build_base_llm(input.model)
```

- [ ] **Step 5: Fix the 6 identical `get_llm` lambda fakes in `tests/test_koda.py`**

Add `AsyncMock` to the top-level imports. Find:

```python
import pytest
import asyncio
import tempfile
import os
from pathlib import Path
```

Replace with:

```python
import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock
```

Then find this exact line (it appears 6 times, in `TestWsEndToEnd` and
`TestWsApprovalGate`, each time directly after a `scripted = ...` line):

```python
        monkeypatch.setattr(an, "get_llm", lambda model=None, enabled_tools=None: scripted)
```

Replace **all 6 occurrences** with:

```python
        monkeypatch.setattr(an, "get_llm", AsyncMock(return_value=scripted))
```

(Use a find-and-replace-all across the file for this exact line — all 6
sites use the same local variable name `scripted`, so the replacement
text is identical every time.)

- [ ] **Step 6: Fix the named `fake_get_llm` function in `tests/test_koda.py`**

Find:

```python
        def fake_get_llm(model=None, enabled_tools=None):
            seen_enabled_tools.append(enabled_tools)
            return scripted

        monkeypatch.setattr(an, "get_llm", fake_get_llm)
```

Replace with:

```python
        async def fake_get_llm(model=None, enabled_tools=None, user_id=None):
            seen_enabled_tools.append(enabled_tools)
            return scripted

        monkeypatch.setattr(an, "get_llm", fake_get_llm)
```

- [ ] **Step 7: Fix the `get_planner_llm` fake in `TestPlannerNode`**

Find:

```python
        monkeypatch.setattr(pn, "get_planner_llm", lambda model=None: FakeLLM())
```

Replace with:

```python
        monkeypatch.setattr(pn, "get_planner_llm", AsyncMock(return_value=FakeLLM()))
```

- [ ] **Step 8: Add a new test for the ValueError→AIMessage catch in `agent_node`**

In `tests/test_koda.py`, right after the `TestAgentPlanPrompt` class
(ends at line ~428, right before `class TestPlanApi:`), insert:

```python
class TestAgentNodeKeyResolutionError:
    @pytest.mark.asyncio
    async def test_unknown_alias_returns_error_message_without_crashing(self, monkeypatch):
        import agent.nodes.agent_node as an

        async def fake_get_llm(*args, **kwargs):
            raise ValueError(
                "No key configured for 'openrouter'. Add one via POST /provider-keys or use a built-in provider."
            )

        monkeypatch.setattr(an, "get_llm", fake_get_llm)

        state = {
            "iterations": 0,
            "max_iterations": 20,
            "cost_usd": 0.0,
            "budget_limit_usd": 2.0,
            "messages": [],
            "workspace_path": "/ws",
            "model": "openrouter/some-model",
            "enabled_tools": None,
            "user_id": "user-1",
        }
        result = await an.agent_node(state)

        assert result["iterations"] == 1
        assert "No key configured for 'openrouter'" in result["messages"][-1].content
```

- [ ] **Step 9: Fix the 3 `_build_base_llm` fakes in `tests/test_vision_describe_tool.py`**

Add `AsyncMock` to the top-level imports. Find:

```python
import pytest

from tools.vision_describe_tool import VisionDescribeTool, VisionDescribeInput
```

Replace with:

```python
import pytest
from unittest.mock import AsyncMock

from tools.vision_describe_tool import VisionDescribeTool, VisionDescribeInput
```

Then find this exact line (appears 3 times: in `test_execute_with_url`,
`test_execute_with_local_file`, `test_execute_llm_failure`):

```python
        monkeypatch.setattr(router, "_build_base_llm", lambda model: fake_llm)
```

Replace **all 3 occurrences** with:

```python
        monkeypatch.setattr(router, "_build_base_llm", AsyncMock(return_value=fake_llm))
```

- [ ] **Step 10: Run the full test suite to verify everything passes**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/integration`
Expected: all pass except the pre-existing, unrelated `TestGraph` /
`TestRouterRegistration` failures (Starlette/FastAPI version mismatch —
tracked separately, not part of this feature; confirm the failure count
and names match what you saw before starting this plan, don't let new
ones sneak in).

- [ ] **Step 11: Commit**

```bash
git add agent/nodes/agent_node.py agent/nodes/planner_node.py agent/nodes/summarize_node.py tools/vision_describe_tool.py tests/test_koda.py tests/test_vision_describe_tool.py
git commit -m "fix: await now-async router functions at every call site"
```

---

### Task 7: Provider-key management routes

**Files:**
- Create: `api/routes/provider_keys.py`
- Modify: `api/main.py`
- Test: `tests/test_provider_keys.py`

**Interfaces:**
- Consumes: `api.deps.get_identity`, `infra.postgres.get_db`,
  `infra.provider_keys_repo.*` (Task 3), `infra.crypto.encrypt_key`
  (Task 1).
- Produces: `POST /api/v1/provider-keys`, `GET /api/v1/provider-keys`,
  `DELETE /api/v1/provider-keys/{alias}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_provider_keys.py`:

```python
class TestProviderKeyRequestValidation:
    def test_rejects_unknown_provider_kind(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="x", provider_kind="not-a-real-kind", api_key="sk-1")

    def test_rejects_empty_alias(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="  ", provider_kind="anthropic", api_key="sk-1")

    def test_rejects_empty_api_key(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="x", provider_kind="anthropic", api_key="  ")

    def test_openai_compatible_requires_base_url(self):
        from pydantic import ValidationError
        from api.routes.provider_keys import ProviderKeyRequest

        with pytest.raises(ValidationError):
            ProviderKeyRequest(alias="openrouter", provider_kind="openai_compatible", api_key="sk-1")

    def test_openai_compatible_with_base_url_is_valid(self):
        from api.routes.provider_keys import ProviderKeyRequest

        req = ProviderKeyRequest(
            alias="openrouter", provider_kind="openai_compatible",
            api_key="sk-1", base_url="https://openrouter.ai/api/v1",
        )
        assert req.base_url == "https://openrouter.ai/api/v1"

    def test_built_in_kind_does_not_require_base_url(self):
        from api.routes.provider_keys import ProviderKeyRequest

        req = ProviderKeyRequest(alias="anthropic", provider_kind="anthropic", api_key="sk-1")
        assert req.base_url is None


class TestProviderKeyRoutes:
    @pytest.mark.asyncio
    async def test_create_encrypts_and_never_echoes_key(self, monkeypatch):
        from unittest.mock import AsyncMock
        from api.routes.provider_keys import create_provider_key, ProviderKeyRequest
        import api.routes.provider_keys as pk_module

        monkeypatch.setattr(pk_module, "encrypt_key", lambda plaintext: "encrypted-" + plaintext)

        captured = {}

        async def fake_create_or_update(db, user_id, alias, provider_kind, api_key_encrypted, base_url):
            captured["api_key_encrypted"] = api_key_encrypted
            row = type("Row", (), {})()
            row.alias = alias
            row.provider_kind = provider_kind
            row.base_url = base_url
            return row

        monkeypatch.setattr(pk_module.provider_keys_repo, "create_or_update", fake_create_or_update)

        body = ProviderKeyRequest(alias="anthropic", provider_kind="anthropic", api_key="sk-plaintext")
        result = await create_provider_key(body, identity=("user-1", "user-1"), db=AsyncMock())

        assert result == {"alias": "anthropic", "provider_kind": "anthropic", "base_url": None}
        assert captured["api_key_encrypted"] == "encrypted-sk-plaintext"
        assert "api_key" not in result
        assert "sk-plaintext" not in str(result)

    @pytest.mark.asyncio
    async def test_list_never_includes_key(self, monkeypatch):
        from unittest.mock import AsyncMock
        from api.routes.provider_keys import list_provider_keys
        import api.routes.provider_keys as pk_module

        row = type("Row", (), {})()
        row.alias = "anthropic"
        row.provider_kind = "anthropic"
        row.base_url = None
        row.created_at = "2026-07-27T00:00:00"

        monkeypatch.setattr(pk_module.provider_keys_repo, "list_for_user", AsyncMock(return_value=[row]))

        result = await list_provider_keys(identity=("user-1", "user-1"), db=AsyncMock())

        assert result == [{
            "alias": "anthropic", "provider_kind": "anthropic",
            "base_url": None, "created_at": "2026-07-27T00:00:00",
        }]

    @pytest.mark.asyncio
    async def test_delete_missing_alias_raises_404(self, monkeypatch):
        from unittest.mock import AsyncMock
        from fastapi import HTTPException
        from api.routes.provider_keys import delete_provider_key
        import api.routes.provider_keys as pk_module

        monkeypatch.setattr(pk_module.provider_keys_repo, "delete_by_alias", AsyncMock(return_value=False))

        with pytest.raises(HTTPException) as exc_info:
            await delete_provider_key("nonexistent", identity=("user-1", "user-1"), db=AsyncMock())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_existing_alias_succeeds(self, monkeypatch):
        from unittest.mock import AsyncMock
        from api.routes.provider_keys import delete_provider_key
        import api.routes.provider_keys as pk_module

        monkeypatch.setattr(pk_module.provider_keys_repo, "delete_by_alias", AsyncMock(return_value=True))

        result = await delete_provider_key("anthropic", identity=("user-1", "user-1"), db=AsyncMock())
        assert result == {"deleted": "anthropic"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py::TestProviderKeyRequestValidation tests/test_provider_keys.py::TestProviderKeyRoutes -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.routes.provider_keys'`

- [ ] **Step 3: Write `api/routes/provider_keys.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_identity
from infra.postgres import get_db
from infra import provider_keys_repo
from infra.crypto import encrypt_key

router = APIRouter()

VALID_PROVIDER_KINDS = {"anthropic", "openai", "gemini", "deepseek", "ollama", "openai_compatible"}


class ProviderKeyRequest(BaseModel):
    alias: str
    provider_kind: str
    api_key: str
    base_url: str | None = None

    @field_validator("alias")
    @classmethod
    def alias_not_empty(cls, v):
        if not v.strip():
            raise ValueError("alias must not be empty")
        return v

    @field_validator("provider_kind")
    @classmethod
    def provider_kind_known(cls, v):
        if v not in VALID_PROVIDER_KINDS:
            raise ValueError(f"provider_kind must be one of {sorted(VALID_PROVIDER_KINDS)}")
        return v

    @field_validator("api_key")
    @classmethod
    def api_key_not_empty(cls, v):
        if not v.strip():
            raise ValueError("api_key must not be empty")
        return v

    @field_validator("base_url")
    @classmethod
    def base_url_required_for_custom(cls, v, info):
        if info.data.get("provider_kind") == "openai_compatible" and not v:
            raise ValueError("base_url is required when provider_kind is 'openai_compatible'")
        return v


@router.post("/provider-keys")
async def create_provider_key(
    body: ProviderKeyRequest,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    _, user_id = identity
    encrypted = encrypt_key(body.api_key)
    row = await provider_keys_repo.create_or_update(
        db, user_id, body.alias, body.provider_kind, encrypted, body.base_url,
    )
    return {
        "alias": row.alias,
        "provider_kind": row.provider_kind,
        "base_url": row.base_url,
    }


@router.get("/provider-keys")
async def list_provider_keys(
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    _, user_id = identity
    rows = await provider_keys_repo.list_for_user(db, user_id)
    return [
        {
            "alias": r.alias,
            "provider_kind": r.provider_kind,
            "base_url": r.base_url,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.delete("/provider-keys/{alias}")
async def delete_provider_key(
    alias: str,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    _, user_id = identity
    deleted = await provider_keys_repo.delete_by_alias(db, user_id, alias)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider key not found")
    return {"deleted": alias}
```

- [ ] **Step 4: Register the router in `api/main.py`**

Find:

```python
from api.routes.ws import router as ws_router
from api.routes.auth import router as auth_router
```

Replace with:

```python
from api.routes.ws import router as ws_router
from api.routes.auth import router as auth_router
from api.routes.provider_keys import router as provider_keys_router
```

Then find:

```python
app.include_router(ws_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
```

Replace with:

```python
app.include_router(ws_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(provider_keys_router, prefix="/api/v1")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_provider_keys.py -v`
Expected: 27 passed (all classes in the file)

- [ ] **Step 6: Commit**

```bash
git add api/routes/provider_keys.py api/main.py tests/test_provider_keys.py
git commit -m "feat: add provider-key management routes for BYOK"
```

---

### Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete unit test suite**

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/integration`

Expected: every test passes except the pre-existing `TestGraph` and
`TestRouterRegistration` failures (Starlette/FastAPI version mismatch,
unrelated to this feature — confirmed present on `main` before this plan
started). If any *other* test fails, that's a regression from this
plan — stop and fix it before moving on.

- [ ] **Step 2: Sanity-check `.env` locally**

Confirm your local `.env` has a real `KEY_ENCRYPTION_SECRET` set (not
just `.env.example`), generated via:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Without it, any real (non-test) call into `infra/crypto.py` raises
`RuntimeError` — expected, but worth confirming deliberately rather than
discovering it at first real use.

- [ ] **Step 3: Final commit (if anything was left uncommitted)**

```bash
git status
```

If clean, nothing to do. If Task 8 fixed something, commit it with a
message describing what the full-suite run caught.

## Out of scope (matches the spec)

- Key rotation/versioning UX.
- Rate limiting or spend caps tied to a user's own key.
- Any frontend/UI — this repo has no frontend; the three routes are the
  complete surface.
- Validating a key actually works at `POST` time.
- Migrating `models.yaml`'s operator keys into this table.
