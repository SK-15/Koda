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
