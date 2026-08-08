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


def gen_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session_token(user_id: str) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + SESSION_TTL_SECONDS}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def decode_session_token(token: str) -> str | None:
    """Return the user_id embedded in a valid, unexpired session token, or None."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")
