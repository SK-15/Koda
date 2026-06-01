from fastapi import APIRouter
from pydantic import BaseModel

from infra.celery_app import celery_app

router = APIRouter()


class StatusResponse(BaseModel):
    task_id: str
    status: str
    result: str | None


@router.get("/status/{task_id}", response_model=StatusResponse)
async def status(task_id: str):
    task = celery_app.AsyncResult(task_id)

    return StatusResponse(
        task_id=task_id,
        status=task.status,
        result=str(task.result) if task.ready() else None,
    )