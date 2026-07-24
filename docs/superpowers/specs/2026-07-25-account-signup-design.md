# Account Signup — Design Spec

**Date:** 2026-07-25
**Status:** Approved
**Execution:** Claude implements end-to-end (explicit override of the default
project pairing rule for this task).

## Goal

Let a user create their own koda account from the browser, instead of the
current admin-only flow (`uv run python -m scripts.create_user <email>`, run
by hand against whichever DB the operator points it at). Also collapse the
current dev/prod Neon database split into a single database everywhere.

## Problem

- `api/routes/auth.py` only exposes `/auth/login`, `/auth/logout`, `/auth/me`.
  Account creation only exists as a CLI script
  (`scripts/create_user.py`), whose docstring is explicit: "admin-provisioned;
  there is no public signup." There's no way to create an account from the
  deployed frontend at all.
- Local `.env`'s `NOEN_CONN_STRING` and the Vercel production project's
  `NOEN_CONN_STRING` point at two different Neon databases. This caused
  confusion when diagnosing a prod 500 (`relation "users" does not exist`) —
  the CLI script was being run against whichever DB happened to be in scope,
  not necessarily the one the deployed backend reads from.

## Decision

### 1. Single Neon database everywhere

Vercel's `NOEN_CONN_STRING` (Production and Preview environments) is updated
to the same value already in local `.env`. `.env.prod` (a temporary file
pulled to diagnose the mismatch) is deleted. Local dev, preview deploys, and
production all now read/write one database.

**Tradeoff accepted:** local testing now creates real "production" rows.
Acceptable at this stage (single user, pre-launch); worth revisiting before
onboarding real users.

### 2. `POST /api/v1/auth/signup` endpoint

Added to `api/routes/auth.py`, alongside the existing `login`/`logout`/`me`.
Reuses the exact same building blocks the CLI script already uses —
`users_repo.create_user` and `infra.auth.hash_password` — so account creation
logic isn't duplicated, only exposed over HTTP.

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

- Pydantic validator enforces the 8-character minimum server-side regardless
  of what the UI does.
- Duplicate email → `409`.
- Success → sets the same session cookie `login` sets (`_set_session_cookie`,
  already defined in this file) — signup auto-logs-in, no separate sign-in
  step required.
- Fully open: no invite code, no admin gate. Matches the "fully open"
  decision made for this task; revisit if abuse becomes a concern.

### 3. Frontend — tab on the existing `LoginView.vue` card

No new route, no new component file.

- A `mode` ref (`'signin' | 'signup'`) drives a small tab row above the
  email/password fields ("Sign in" / "Create account").
- Same two fields serve both modes. Submit handler branches on `mode`,
  calling either `api.login()` (existing) or the new `api.signup()`.
- `api.ts` gets:
  ```typescript
  export function signup(email: string, password: string): Promise<AuthUser> {
    return request<AuthUser>('/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  }
  ```
  Same `request()` helper as every other call — cookie-based session applies
  identically.
- On success, `LoginView` emits the same `logged-in` event it already emits
  for sign-in. `App.vue` needs no changes — it already reacts to that event
  regardless of which flow produced it.
- Error display reuses the existing `.error` paragraph. Signup shows the
  server's `detail` text (e.g. "Email already registered") instead of the
  generic "Invalid email or password" string, which stays login-only.
- Client-side: submit disabled (or inline hint shown) when the signup
  password is under 8 characters, mirroring the server-side rule so the user
  gets instant feedback instead of waiting for a 422.

## Error handling

| Case | Response |
|---|---|
| Password < 8 chars (signup) | `422` (pydantic validation) |
| Email already registered | `409` |
| Wrong credentials (login, unchanged) | `401` |
| Signup success | `200`, session cookie set, `{user_id, email}` body |

## Testing

- Backend: extend `tests/test_koda.py`'s auth test class —
  `test_signup_creates_user_and_sets_cookie`,
  `test_signup_duplicate_email_409`,
  `test_signup_short_password_422`.
- Frontend: manual verification only (no existing frontend test suite for
  `LoginView.vue` to extend) — sign up with a new email locally, confirm
  auto-login and that the sidebar shows the new user's email; try a
  duplicate email and confirm the inline error renders.

## Files touched

| File | Change |
|---|---|
| `api/routes/auth.py` | add `SignupRequest`, `POST /auth/signup` |
| `tests/test_koda.py` | new signup test cases |
| `koda-app/src/components/LoginView.vue` | add sign-in/signup tab, branch submit handler |
| `koda-app/src/api.ts` | add `signup()` |
| Vercel dashboard (`koda` project) | `NOEN_CONN_STRING` set to the same value as local `.env`, for Production + Preview |
| `.env.prod` (local, gitignored) | deleted — no longer needed once there's one DB |

## Out of scope

- Invite codes / admin approval gating (explicitly rejected for this task).
- Password reset / forgot-password flow.
- Email verification.
- Rate limiting the signup endpoint.
- Any change to `/auth/login`, `/auth/logout`, or `/auth/me` behavior.
