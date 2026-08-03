import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.postgres import User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password_hash: str) -> User:
    user = User(user_id=str(uuid.uuid4()), email=email, password_hash=password_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_by_sub(db: AsyncSession, user_id: str, email: str) -> User:
    user = await get_user_by_id(db, user_id)
    if user is not None:
        return user
    user = User(user_id=user_id, email=email, password_hash=None)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
