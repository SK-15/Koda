from fastapi import HTTPException, Request

from infra.auth import COOKIE_NAME, decode_session_token


async def get_identity(request: Request) -> tuple[str, str]:
    """Resolve (org_id, user_id) from the session cookie. Data is scoped per-user,
    so org_id and user_id are always the same value."""
    token = request.cookies.get(COOKIE_NAME)
    user_id = decode_session_token(token) if token else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id, user_id
