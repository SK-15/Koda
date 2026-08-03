import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from infra import refresh_tokens_repo, users_repo
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
from infra.postgres import get_db

router = APIRouter()


class ExchangeRequest(BaseModel):
    neon_token: str


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
