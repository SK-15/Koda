import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from infra import refresh_tokens_repo, users_repo
from infra.auth import (
    COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    REFRESH_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    create_session_token,
    decode_session_token,
    gen_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from infra.postgres import get_db

router = APIRouter()

# Precomputed once at import time so a login attempt against a nonexistent
# user still pays the cost of one bcrypt comparison (timing-uniform with a
# real user's login), without hashing a fresh dummy password per request.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-login")


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session_token(user_id),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="none",
        path="/auth",
    )


async def _issue_session(db: AsyncSession, response: Response, user_id: str, family_id: str) -> None:
    token = gen_refresh_token()
    await refresh_tokens_repo.create(db, user_id, family_id, hash_token(token), REFRESH_TTL_SECONDS)
    _set_session_cookie(response, user_id)
    _set_refresh_cookie(response, token)


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await users_repo.get_user_by_email(db, body.email)
    stored_hash = user.password_hash if (user and user.password_hash) else _DUMMY_PASSWORD_HASH
    password_ok = await run_in_threadpool(verify_password, body.password, stored_hash)
    if user is None or not user.password_hash or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await _issue_session(db, response, user.user_id, str(uuid.uuid4()))
    return {"user_id": user.user_id, "email": user.email}


@router.post("/auth/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = await refresh_tokens_repo.get_by_hash(db, hash_token(token))
    if row is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if row.revoked_at is not None:
        # Reuse of a rotated-out token — signals theft, kill the whole chain.
        await refresh_tokens_repo.revoke_family(db, row.family_id)
        raise HTTPException(status_code=401, detail="Not authenticated")

    if row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Not authenticated")

    await refresh_tokens_repo.revoke(db, row)
    await _issue_session(db, response, row.user_id, row.family_id)
    return {"status": "ok"}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if token:
        row = await refresh_tokens_repo.get_by_hash(db, hash_token(token))
        if row is not None:
            await refresh_tokens_repo.revoke_family(db, row.family_id)

    response.delete_cookie(key=COOKIE_NAME, path="/", secure=True, samesite="none")
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/auth", secure=True, samesite="none")
    return {"status": "ok"}


@router.get("/auth/me")
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(COOKIE_NAME)
    user_id = decode_session_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await users_repo.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return {"user_id": user.user_id, "email": user.email}
