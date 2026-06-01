import uuid
from fastapi import APIRouter, Request
from pydantic import BaseModel

from infra.celery_app import run_graph_task

router = APIRouter()


class RunRequest(BaseModel):
    message: str
    workspace_path: str
    org_id: str = "default"
    user_id: str = "default"
    budget_limit_usd: float = 2.00
    max_iterations: int = 20


class RunResponse(BaseModel):
    thread_id: str
    task_id: str
    status: str


@router.post("/run", response_model=RunResponse)
async def run(request: RunRequest):
    thread_id = f"{request.org_id}:{request.user_id}:{uuid.uuid4()}"

    task = run_graph_task.delay(
        thread_id=thread_id,
        message=request.message,
        workspace_path=request.workspace_path,
        org_id=request.org_id,
        user_id=request.user_id,
        budget_limit_usd=request.budget_limit_usd,
        max_iterations=request.max_iterations,
    )

    return RunResponse(
        thread_id=thread_id,
        task_id=task.id,
        status="queued",
    )