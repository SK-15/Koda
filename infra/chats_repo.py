import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from infra.postgres import ThreadRecord


async def create_chat(
    db: AsyncSession,
    project_id: str,
    org_id: str,
    user_id: str,
    title: str | None = None,
) -> ThreadRecord:
    chat = ThreadRecord(
        thread_id=str(uuid.uuid4()),
        project_id=project_id,
        org_id=org_id,
        user_id=user_id,
        title=title,
        cost_usd=0.0,
        tokens_used=0,
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def list_chats(
    db: AsyncSession, project_id: str, org_id: str, user_id: str
) -> list[ThreadRecord]:
    result = await db.execute(
        select(ThreadRecord)
        .where(
            ThreadRecord.project_id == project_id,
            ThreadRecord.org_id == org_id,
            ThreadRecord.user_id == user_id,
        )
        .order_by(ThreadRecord.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_chat(
    db: AsyncSession, chat_id: str, org_id: str, user_id: str
) -> ThreadRecord | None:
    result = await db.execute(
        select(ThreadRecord).where(
            ThreadRecord.thread_id == chat_id,
            ThreadRecord.org_id == org_id,
            ThreadRecord.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_chat_meta(
    db: AsyncSession,
    chat_id: str,
    last_message: str,
    title: str | None = None,
) -> None:
    result = await db.execute(
        select(ThreadRecord).where(ThreadRecord.thread_id == chat_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return
    row.last_message = last_message[:500]
    if title is not None and row.title is None:
        row.title = title[:80]
    await db.commit()
