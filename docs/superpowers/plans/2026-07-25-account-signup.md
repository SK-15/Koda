# Account Signup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users create their own koda account from the browser (public signup, auto-login on success), and collapse the dev/prod Neon database split into one database.

**Architecture:** A new `POST /api/v1/auth/signup` FastAPI route reuses the existing `users_repo.create_user` + `infra.auth.hash_password` building blocks and sets the same session cookie `login` already sets. The frontend adds a sign-in/signup tab to the existing `LoginView.vue` card — no new route or component. Separately, Vercel's `NOEN_CONN_STRING` is updated to match local `.env` so there's a single Neon database everywhere.

**Tech Stack:** FastAPI, SQLAlchemy (async), pydantic v2, pytest + pytest-asyncio, Vue 3 `<script setup>`, TypeScript, Vercel CLI.

## Global Constraints

- Signup is fully open — no invite code, no admin gate (spec decision).
- Password minimum 8 characters, enforced both client-side (instant feedback) and server-side (pydantic validator, so it holds even if the UI is bypassed).
- Duplicate email on signup → `409`. Wrong login credentials stay `401` (unchanged).
- No new frontend route/component — signup lives as a tab on the existing `LoginView.vue` card.
- Spec: `docs/superpowers/specs/2026-07-25-account-signup-design.md`.

---

### Task 1: Backend `POST /auth/signup` route

**Files:**
- Modify: `api/routes/auth.py`
- Test: `tests/test_koda.py` (extend `TestAuthRoute`, ~line 592)

**Interfaces:**
- Consumes: `users_repo.get_user_by_email(db, email)`, `users_repo.create_user(db, email, password_hash)` (existing, `infra/users_repo.py`), `hash_password(password)` (existing, `infra/auth.py`), `_set_session_cookie(response, user_id)` (existing, same file, `api/routes/auth.py:23-32`).
- Produces: `signup(body: SignupRequest, response: Response, db: AsyncSession) -> dict` and `SignupRequest` (email, password) — the frontend task (Task 3) calls this route by HTTP path `/auth/signup`, not by importing the function.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_koda.py`, inside `class TestAuthRoute` (after `test_login_sets_cookie_on_success`, ~line 591):

```python
    @pytest.mark.asyncio
    async def test_signup_creates_user_and_sets_cookie(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from fastapi import Response
        from api.routes.auth import signup, SignupRequest
        import api.routes.auth as auth_module
        from infra.auth import COOKIE_NAME

        monkeypatch.setenv("JWT_SECRET", "test-secret")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute.return_value = mock_result

        created_user = MagicMock()
        created_user.user_id = "user-456"
        created_user.email = "new@example.com"
        monkeypatch.setattr(
            auth_module.users_repo, "create_user",
            AsyncMock(return_value=created_user),
        )

        response = Response()
        result = await signup(
            SignupRequest(email="new@example.com", password="longenough"),
            response, session,
        )
        assert result == {"user_id": "user-456", "email": "new@example.com"}
        assert COOKIE_NAME in response.headers.get("set-cookie", "")

    @pytest.mark.asyncio
    async def test_signup_rejects_duplicate_email(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from fastapi import HTTPException, Response
        from api.routes.auth import signup, SignupRequest

        existing_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        session = AsyncMock()
        session.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await signup(
                SignupRequest(email="dup@example.com", password="longenough"),
                Response(), session,
            )
        assert exc_info.value.status_code == 409

    def test_signup_request_rejects_short_password(self):
        from pydantic import ValidationError
        from api.routes.auth import SignupRequest

        with pytest.raises(ValidationError):
            SignupRequest(email="a@b.com", password="short")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/saurav/Projects/koda && uv run pytest tests/test_koda.py -k signup -v`
Expected: 3 failures — `signup`/`SignupRequest` not defined (ImportError/AttributeError).

- [ ] **Step 3: Implement `SignupRequest` and `signup` route**

In `api/routes/auth.py`, change the imports at the top:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
```

Add `SignupRequest` right after `LoginRequest` (~line 21):

```python
class SignupRequest(BaseModel):
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v
```

Add the `signup` route right after `login` (~line 47, before `logout`):

```python
@router.post("/auth/signup")
async def signup(
    body: SignupRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    existing = await users_repo.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await users_repo.create_user(db, body.email, hash_password(body.password))
    _set_session_cookie(response, user.user_id)
    return {"user_id": user.user_id, "email": user.email}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/saurav/Projects/koda && uv run pytest tests/test_koda.py -k signup -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full auth test file to check nothing broke**

Run: `cd /home/saurav/Projects/koda && uv run pytest tests/test_koda.py -k "Auth or auth" -v`
Expected: all pass (existing login/logout/me tests + new signup tests).

- [ ] **Step 6: Commit**

```bash
git add api/routes/auth.py tests/test_koda.py
git commit -m "$(cat <<'EOF'
feat: add POST /auth/signup route

Public signup, reuses existing users_repo/hash_password, auto-logs in
via the same session cookie login sets.
EOF
)"
```

---

### Task 2: Frontend `api.signup()` call

**Files:**
- Modify: `koda-app/src/api.ts`

**Interfaces:**
- Consumes: `request<T>(path, init)` (existing, `koda-app/src/api.ts:13-30`), `AuthUser` type (existing, `koda-app/src/types.ts`).
- Produces: `signup(email: string, password: string): Promise<AuthUser>` — consumed by Task 3's `LoginView.vue`.

- [ ] **Step 1: Add `signup()` next to the existing `login()`**

In `koda-app/src/api.ts`, right after the `login` function (~line 39):

```typescript
export function signup(email: string, password: string): Promise<AuthUser> {
  return request<AuthUser>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}
```

- [ ] **Step 2: Type-check**

Run: `cd /home/saurav/Projects/koda-app && npx vue-tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add src/api.ts
git commit -m "feat: add signup() API call"
```

---

### Task 3: Frontend sign-in/signup tab on `LoginView.vue`

**Files:**
- Modify: `koda-app/src/components/LoginView.vue`

**Interfaces:**
- Consumes: `api.login(email, password)`, `api.signup(email, password)` (Task 2), both `Promise<AuthUser>`.
- Produces: unchanged `logged-in` event contract — `App.vue` needs no changes.

- [ ] **Step 1: Replace the full file with the tab-aware version**

Replace `koda-app/src/components/LoginView.vue` entirely with:

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import * as api from '../api'
import type { AuthUser } from '../types'

const emit = defineEmits<{
  (e: 'logged-in', user: AuthUser): void
}>()

const mode = ref<'signin' | 'signup'>('signin')
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

const passwordTooShort = computed(
  () => mode.value === 'signup' && password.value.length > 0 && password.value.length < 8,
)

function switchMode(next: 'signin' | 'signup') {
  mode.value = next
  error.value = ''
}

async function submit() {
  if (!email.value.trim() || !password.value || busy.value) return
  if (mode.value === 'signup' && password.value.length < 8) {
    error.value = 'Password must be at least 8 characters'
    return
  }
  error.value = ''
  busy.value = true
  try {
    const user = mode.value === 'signin'
      ? await api.login(email.value.trim(), password.value)
      : await api.signup(email.value.trim(), password.value)
    emit('logged-in', user)
  } catch (err) {
    error.value = mode.value === 'signin'
      ? 'Invalid email or password'
      : (err instanceof Error ? err.message : 'Could not create account')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-screen">
    <form class="login-card" @submit.prevent="submit">
      <div class="brand-row">
        <div class="mark">k</div>
        <span class="wordmark">koda</span>
      </div>

      <div class="tab-row">
        <button
          type="button"
          class="tab"
          :class="{ active: mode === 'signin' }"
          @click="switchMode('signin')"
        >Sign in</button>
        <button
          type="button"
          class="tab"
          :class="{ active: mode === 'signup' }"
          @click="switchMode('signup')"
        >Create account</button>
      </div>

      <label class="field">
        <span class="field-label">Email</span>
        <input v-model="email" type="email" autocomplete="username" autofocus />
      </label>
      <label class="field">
        <span class="field-label">Password</span>
        <input
          v-model="password"
          type="password"
          :autocomplete="mode === 'signin' ? 'current-password' : 'new-password'"
        />
      </label>
      <p v-if="passwordTooShort" class="hint">At least 8 characters</p>

      <p v-if="error" class="error">{{ error }}</p>

      <button type="submit" class="submit" :disabled="busy">
        {{ busy
          ? (mode === 'signin' ? 'Signing in…' : 'Creating account…')
          : (mode === 'signin' ? 'Sign in' : 'Create account') }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login-screen {
  height: 100vh;
  width: 100vw;
  display: grid;
  place-items: center;
  background: var(--bg-deep);
}
.login-card {
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 28px 24px;
  border-radius: 14px;
  background: var(--panel-2);
  border: 1px solid var(--border-2);
  box-shadow: var(--shadow-soft);
}
.brand-row {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 8px;
}
.mark {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--accent);
  display: grid;
  place-items: center;
  font: 600 14px var(--font-mono);
  color: #0a0f0d;
}
.wordmark {
  font: 600 15px var(--font-mono);
  letter-spacing: 0.02em;
  color: var(--text);
}
.tab-row {
  display: flex;
  gap: 4px;
  padding: 3px;
  border-radius: 8px;
  background: var(--panel);
  border: 1px solid var(--border);
  margin-bottom: 4px;
}
.tab {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12.5px;
  font-weight: 600;
  padding: 7px 0;
  border-radius: 6px;
  cursor: pointer;
}
.tab.active {
  background: var(--panel-2);
  color: var(--text);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  font-size: 12px;
  color: var(--text-dim);
}
.field input {
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}
.field input:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.hint {
  margin: -8px 0 0;
  font-size: 11.5px;
  color: var(--text-dim);
}
.error {
  margin: 0;
  font-size: 12.5px;
  color: oklch(0.7 0.18 25);
}
.submit {
  margin-top: 4px;
  border: none;
  border-radius: 8px;
  padding: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  background: var(--accent-grad);
  color: #0a0f0d;
}
.submit:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
```

- [ ] **Step 2: Type-check**

Run: `cd /home/saurav/Projects/koda-app && npx vue-tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Manual local check**

Run: `cd /home/saurav/Projects/koda-app && npm run dev`, open the printed localhost URL. Confirm:
- Card shows "Sign in" / "Create account" tabs, "Sign in" active by default.
- Clicking "Create account" swaps the submit button label and clears any error.
- Typing a password under 8 chars in signup mode shows the "At least 8 characters" hint.

Stop the dev server after checking (`Ctrl+C`).

- [ ] **Step 4: Commit**

```bash
git add src/components/LoginView.vue
git commit -m "feat: add sign-in/signup tab to LoginView"
```

---

### Task 4: Collapse to a single Neon database

**Files:**
- None (Vercel dashboard/env config only, plus deleting a local file)

**Interfaces:**
- Consumes: local `.env`'s `NOEN_CONN_STRING` value (read, never printed to chat).
- Produces: Vercel `koda` project's `NOEN_CONN_STRING` (Production + Preview) matches local `.env`. No code depends on this directly — `infra/postgres.py` already reads `NOEN_CONN_STRING` from the environment.

- [ ] **Step 1: Remove the existing Vercel env values**

```bash
cd /home/saurav/Projects/koda
npx vercel env rm NOEN_CONN_STRING production --yes
npx vercel env rm NOEN_CONN_STRING preview --yes
```

- [ ] **Step 2: Add the local `.env` value for both environments**

```bash
NEW_VAL=$(grep '^NOEN_CONN_STRING=' .env | cut -d= -f2-)
printf '%s' "$NEW_VAL" | npx vercel env add NOEN_CONN_STRING production
printf '%s' "$NEW_VAL" | npx vercel env add NOEN_CONN_STRING preview
unset NEW_VAL
```

- [ ] **Step 3: Verify (names/environments only, not values)**

Run: `npx vercel env ls production 2>&1 | grep NOEN_CONN_STRING`
Expected: `NOEN_CONN_STRING  Encrypted  Production, Preview  <just now>`

- [ ] **Step 4: Redeploy backend so the new env var takes effect**

```bash
npx vercel --prod
```

- [ ] **Step 5: Delete the now-unneeded diagnostic file**

```bash
rm .env.prod
```

(Already gitignored — nothing to unstage.)

- [ ] **Step 6: No commit needed** — this task changes no tracked files (`.env.prod` was already untracked/gitignored).

---

### Task 5: End-to-end verification

**Files:** none (verification only)

**Interfaces:** none produced — terminal task.

- [ ] **Step 1: Push backend + frontend commits**

```bash
cd /home/saurav/Projects/koda && git push origin main
cd /home/saurav/Projects/koda-app && git push origin main
```

- [ ] **Step 2: Redeploy frontend** (no git-integration auto-deploy configured, per earlier session notes)

```bash
cd /home/saurav/Projects/koda-app && npx vercel --prod
```

- [ ] **Step 3: Verify signup end-to-end via curl** (no real password ever typed by Claude — this uses a disposable test account, not the user's)

```bash
curl -s -X POST https://koda-navy-five.vercel.app/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"e2e-test@example.com","password":"testpass123"}' -w '\n%{http_code}\n'
```
Expected: `200` with `{"user_id": "...", "email": "e2e-test@example.com"}`.

- [ ] **Step 4: Verify duplicate-email rejection**

```bash
curl -s -X POST https://koda-navy-five.vercel.app/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"e2e-test@example.com","password":"testpass123"}' -w '\n%{http_code}\n'
```
Expected: `409`.

- [ ] **Step 5: Browser check of the deployed frontend**

Using claude-in-chrome tools: navigate to `https://koda-app-rust.vercel.app`, click "Create account", sign up with a fresh test email (e.g. `e2e-browser@example.com` / `testpass123`), confirm it auto-logs in (sidebar shows the new email, login card disappears). Screenshot as evidence.

- [ ] **Step 6: Report results to the user**

Summarize: tests passed, both repos deployed, curl + browser verification results, and remind the user that `e2e-test@example.com` / `e2e-browser@example.com` are now real rows in the (now single) Neon database if they want to delete them later.

---

## Out of scope (per spec)

- Invite codes / admin approval gating.
- Password reset / forgot-password flow.
- Email verification.
- Rate limiting the signup endpoint.
