from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from api.deps import get_identity
from infra.postgres import get_db, ThreadRecord
from infra import projects_repo

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str
    workspace_path: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("name must not be empty")
        return v

    @field_validator("workspace_path")
    @classmethod
    def workspace_not_empty(cls, v):
        if not v.strip():
            raise ValueError("workspace_path must not be empty")
        return v


@router.post("/projects")
async def create_project(
    body: CreateProjectRequest,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    project = await projects_repo.create_project(
        db, org_id, user_id, body.name, body.workspace_path
    )
    return {
        "project_id": project.project_id,
        "name": project.name,
        "workspace_path": project.workspace_path,
        "created_at": project.created_at,
    }


@router.get("/projects")
async def list_projects(
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    projects = await projects_repo.list_projects(db, org_id, user_id)
    return [
        {
            "project_id": p.project_id,
            "name": p.name,
            "workspace_path": p.workspace_path,
            "created_at": p.created_at,
        }
        for p in projects
    ]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    project = await projects_repo.get_project(db, project_id, org_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    count_result = await db.execute(
        select(func.count()).where(ThreadRecord.project_id == project_id)
    )
    chat_count = count_result.scalar() or 0

    return {
        "project_id": project.project_id,
        "name": project.name,
        "workspace_path": project.workspace_path,
        "created_at": project.created_at,
        "chat_count": chat_count,
    }
