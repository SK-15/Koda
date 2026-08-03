import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres import RefreshToken


async def create(db: AsyncSession, user_id: str, family_id: str, token_hash: str, ttl_seconds: int) -> RefreshToken:
    row = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        family_id=family_id,
        token_hash=token_hash,
        expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_by_hash(db: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    return result.scalar_one_or_none()


async def revoke(db: AsyncSession, row: RefreshToken) -> None:
    row.revoked_at = datetime.utcnow()
    await db.commit()


async def revoke_family(db: AsyncSession, family_id: str) -> None:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
    )
    for row in result.scalars().all():
        row.revoked_at = datetime.utcnow()
    await db.commit()
