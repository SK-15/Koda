# Backend-Owned Auth (Drop Neon JWKS) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Neon-Auth-token exchange (`POST /auth/exchange`, JWKS verification) with backend-owned email+password login (`POST /auth/login`), using the DB columns and helper functions that already exist but are unused.

**Architecture:** `koda`'s own `users` table (already has `password_hash`) becomes the sole identity store. `POST /auth/login` looks up the user by email and checks the password with the existing `verify_password` (bcrypt) helper, then reuses the existing `_issue_session()` helper — unchanged — to set the session-JWT cookie and rotating refresh-token-family cookie. `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` are untouched; they never depended on Neon. Signup stays admin-only via the existing `scripts/create_user.py` CLI — no public signup endpoint.

**Tech Stack:** FastAPI, SQLAlchemy async, bcrypt, PyJWT (HS256 session tokens only — the JWKS/RS256 client is removed), pytest + pytest-asyncio.

## Global Constraints

- No new dependencies — `bcrypt` and `pyjwt` are already in `pyproject.toml`.
- No public signup endpoint — accounts are created only via `uv run python -m scripts.create_user <email>`.
- Login failures (unknown email, wrong password, or a user with no password set) must all return the same generic `401 "Invalid email or password"` — do not leak which case occurred.
- Do not touch `.env` — flag `NEON_JWKS_URL`/`NEON_AUTH_URL` as dead but leave removal to the user.
- Tests call route functions directly (no `TestClient`), matching the existing pattern in `tests/test_koda.py` (`AsyncMock()` for the DB session, `monkeypatch` on `auth_module.<repo>.<fn>`).

---

### Task 1: Strip Neon JWKS verification from `infra/auth.py`

**Files:**
- Modify: `infra/auth.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (unchanged, still used by Task 3 and existing routes): `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool`, `gen_refresh_token() -> str`, `hash_token(token: str) -> str`, `create_session_token(user_id: str) -> str`, `decode_session_token(token: str) -> str | None`, constants `COOKIE_NAME`, `REFRESH_COOKIE_NAME`, `SESSION_TTL_SECONDS`, `REFRESH_TTL_SECONDS`.
- Removed (no longer exist after this task — later tasks must not reference them): `verify_neon_token`, `_jwks`, `_jwks_client`.

- [ ] **Step 1: Remove the JWKS client and verifier**

In `infra/auth.py`, delete these pieces:
- The `import jwt` stays (still used for HS256 session tokens) but drop the now-unused `_jwks_client` global, the `_jwks()` function, and `verify_neon_token()`.

The file's top (imports + globals) should read:

```python
import hashlib
import os
import secrets
import time

import bcrypt
import jwt

JWT_ALG = "HS256"
SESSION_TTL_SECONDS = 15 * 60  # 15 minutes — refresh token covers the rest
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
COOKIE_NAME = "koda_session"
REFRESH_COOKIE_NAME = "koda_refresh"


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET not set. Add it to .env")
    return secret
```

Everything below `_secret()` (`gen_refresh_token`, `hash_token`, `hash_password`, `verify_password`, `create_session_token`, `decode_session_token`) stays exactly as-is — do not modify those functions.

- [ ] **Step 2: Verify the module still imports cleanly**

Run: `python -c "import infra.auth"`
Expected: no output, exit code 0 (no `PyJWKClient`/JWKS references remain to break the import).

- [ ] **Step 3: Commit**

```bash
git add infra/auth.py
git commit -m "refactor: drop Neon JWKS verification from infra/auth"
```

---

### Task 2: Remove the now-unused `get_or_create_by_sub` from `infra/users_repo.py`

**Files:**
- Modify: `infra/users_repo.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (unchanged, used by Task 3): `get_user_by_email(db, email) -> User | None`, `get_user_by_id(db, user_id) -> User | None`, `create_user(db, email, password_hash) -> User`.
- Removed: `get_or_create_by_sub` (its only caller, `/auth/exchange`, is deleted in Task 3).

- [ ] **Step 1: Delete `get_or_create_by_sub`**

Remove this function from `infra/users_repo.py`:

```python
async def get_or_create_by_sub(db: AsyncSession, user_id: str, email: str) -> User:
    user = await get_user_by_id(db, user_id)
    if user is not None:
        return user
    user = User(user_id=user_id, email=email, password_hash=None)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
```

The `import uuid` at the top of the file is still needed by `create_user` — leave it.

- [ ] **Step 2: Verify the module still imports cleanly**

Run: `python -c "import infra.users_repo"`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
git add infra/users_repo.py
git commit -m "refactor: remove unused get_or_create_by_sub"
```

---

### Task 3: Replace `POST /auth/exchange` with `POST /auth/login` in `api/routes/auth.py`

**Files:**
- Modify: `api/routes/auth.py`

**Interfaces:**
- Consumes: `infra.auth.verify_password`, `infra.users_repo.get_user_by_email` (both already exist), `infra.auth.hash_password` is NOT needed here (login only checks, doesn't create).
- Produces: `POST /auth/login` route function named `login`, request model `LoginRequest(email: str, password: str)`. `_issue_session`, `_set_session_cookie`, `_set_refresh_cookie` are unchanged and still used.
- Removed: `ExchangeRequest`, the `exchange` route function, the `verify_neon_token` import.

- [ ] **Step 1: Update imports**

In `api/routes/auth.py`, change:

```python
from infra.auth import (
    COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    REFRESH_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    create_session_token,
    decode_session_token,
    gen_refresh_token,
    hash_token,
    verify_neon_token,
)
```

to:

```python
from infra.auth import (
    COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    REFRESH_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    create_session_token,
    decode_session_token,
    gen_refresh_token,
    hash_token,
    verify_password,
)
```

- [ ] **Step 2: Replace `ExchangeRequest` and the `exchange` route**

Delete:

```python
class ExchangeRequest(BaseModel):
    neon_token: str
```

and:

```python
@router.post("/auth/exchange")
async def exchange(
    body: ExchangeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        claims = verify_neon_token(body.neon_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Neon Auth token")

    user_id = claims.get("sub")
    email = claims.get("email")
    if not user_id or not email:
        raise HTTPException(status_code=401, detail="Invalid Neon Auth token")

    user = await users_repo.get_or_create_by_sub(db, user_id, email)
    await _issue_session(db, response, user.user_id, str(uuid.uuid4()))
    return {"user_id": user.user_id, "email": user.email}
```

Replace both with:

```python
class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await users_repo.get_user_by_email(db, body.email)
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await _issue_session(db, response, user.user_id, str(uuid.uuid4()))
    return {"user_id": user.user_id, "email": user.email}
```

Place it where `exchange` used to be (right after `_issue_session`, before `/auth/refresh`). `uuid` is still imported at the top of the file and still used here.

- [ ] **Step 3: Verify the module still imports cleanly**

Run: `python -c "import api.routes.auth"`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add api/routes/auth.py
git commit -m "feat: replace Neon token exchange with local email/password login"
```

---

### Task 4: Update tests for `/auth/login`

**Files:**
- Modify: `tests/test_koda.py:575-618` (the `test_exchange_rejects_invalid_neon_token` and `test_exchange_creates_user_and_sets_both_cookies` tests inside `class TestAuthRoute`)

**Interfaces:**
- Consumes: `api.routes.auth.login`, `api.routes.auth.LoginRequest`, `api.routes.auth.users_repo.get_user_by_email`, `infra.auth.COOKIE_NAME`, `infra.auth.REFRESH_COOKIE_NAME`.

- [ ] **Step 1: Write the replacement tests**

In `tests/test_koda.py`, replace the two exchange tests (currently at lines 575-618) with:

```python
    @pytest.mark.asyncio
    async def test_login_rejects_unknown_email(self, monkeypatch):
        from unittest.mock import AsyncMock
        from fastapi import HTTPException, Response
        from api.routes.auth import login, LoginRequest
        import api.routes.auth as auth_module

        monkeypatch.setattr(
            auth_module.users_repo, "get_user_by_email",
            AsyncMock(return_value=None),
        )

        with pytest.raises(HTTPException) as exc_info:
            await login(LoginRequest(email="nobody@x.com", password="whatever"), Response(), AsyncMock())
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid email or password"

    @pytest.mark.asyncio
    async def test_login_rejects_wrong_password(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from fastapi import HTTPException, Response
        from api.routes.auth import login, LoginRequest
        import api.routes.auth as auth_module
        from infra.auth import hash_password

        user = MagicMock()
        user.user_id = "user-123"
        user.email = "a@b.com"
        user.password_hash = hash_password("correct-horse")
        monkeypatch.setattr(
            auth_module.users_repo, "get_user_by_email",
            AsyncMock(return_value=user),
        )

        with pytest.raises(HTTPException) as exc_info:
            await login(LoginRequest(email="a@b.com", password="wrong-guess"), Response(), AsyncMock())
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid email or password"

    @pytest.mark.asyncio
    async def test_login_accepts_correct_password_and_sets_both_cookies(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from fastapi import Response
        from api.routes.auth import login, LoginRequest
        import api.routes.auth as auth_module
        from infra.auth import COOKIE_NAME, REFRESH_COOKIE_NAME, hash_password

        monkeypatch.setenv("JWT_SECRET", "test-secret")

        user = MagicMock()
        user.user_id = "user-123"
        user.email = "a@b.com"
        user.password_hash = hash_password("correct-horse")
        monkeypatch.setattr(
            auth_module.users_repo, "get_user_by_email",
            AsyncMock(return_value=user),
        )
        monkeypatch.setattr(
            auth_module.refresh_tokens_repo, "create", AsyncMock(),
        )

        response = Response()
        result = await login(LoginRequest(email="a@b.com", password="correct-horse"), response, AsyncMock())
        assert result == {"user_id": "user-123", "email": "a@b.com"}
        set_cookie_headers = response.headers.getlist("set-cookie")
        assert any(COOKIE_NAME in h for h in set_cookie_headers)
        assert any(REFRESH_COOKIE_NAME in h for h in set_cookie_headers)
```

- [ ] **Step 2: Run the auth test class**

Run: `pytest tests/test_koda.py::TestAuthRoute -v`
Expected: all tests PASS (the three new login tests plus the untouched refresh/logout/me tests below them).

- [ ] **Step 3: Run the full test file to confirm nothing else references the removed code**

Run: `pytest tests/test_koda.py -v`
Expected: all tests PASS, no `ImportError`/`AttributeError` for `verify_neon_token`, `ExchangeRequest`, `exchange`, or `get_or_create_by_sub`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_koda.py
git commit -m "test: replace exchange tests with login tests"
```

---

### Task 5: Full-repo sanity sweep for leftover references

**Files:**
- None expected to change — this is a verification-only task. If it finds a leftover reference, fix it in the file it's found in.

- [ ] **Step 1: Grep for anything still referencing the removed names**

Run:
```bash
grep -rn "verify_neon_token\|ExchangeRequest\|neon_token\|get_or_create_by_sub\|/auth/exchange" --include=*.py .
```
Expected: no matches outside `.venv`. If any turn up, delete/update that reference and re-run the grep until clean.

- [ ] **Step 2: Run the full test suite one more time**

Run: `pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 3: Commit (only if Step 1 required fixes)**

```bash
git add -A
git commit -m "chore: sweep leftover Neon-exchange references"
```
