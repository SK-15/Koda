from fastapi import APIRouter
from pydantic import BaseModel
from infra.task_store import get_task_status

router = APIRouter()


class StatusResponse(BaseModel):
    task_id: str
    status: str
    result: str | None


@router.get("/status/{task_id}", response_model=StatusResponse)
async def status(task_id: str):
    task = await get_task_status(task_id)
    return StatusResponse(
        task_id=task_id,
        status=task["status"],
        result=task["result"],
    )