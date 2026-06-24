import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from infra.postgres import Project


async def create_project(
    db: AsyncSession,
    org_id: str,
    user_id: str,
    name: str,
    workspace_path: str,
) -> Project:
    project = Project(
        project_id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        name=name,
        workspace_path=workspace_path,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def list_projects(db: AsyncSession, org_id: str, user_id: str) -> list[Project]:
    result = await db.execute(
        select(Project)
        .where(Project.org_id == org_id, Project.user_id == user_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars().all())


async def get_project(
    db: AsyncSession, project_id: str, org_id: str, user_id: str
) -> Project | None:
    result = await db.execute(
        select(Project).where(
            Project.project_id == project_id,
            Project.org_id == org_id,
            Project.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()
