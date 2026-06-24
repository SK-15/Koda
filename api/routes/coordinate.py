from fastapi import APIRouter
from pydantic import BaseModel
from coordinator.coordinator import Coordinator

router = APIRouter()


class CoordinateRequest(BaseModel):
    task: str
    workspace_path: str
    org_id: str = "default"
    user_id: str = "default"
    max_workers: int = 5


@router.post("/coordinate")
async def coordinate(request: CoordinateRequest):
    coordinator = Coordinator(
        workspace_path=request.workspace_path,
        org_id=request.org_id,
        user_id=request.user_id,
        max_workers=request.max_workers,
    )
    result = await coordinator.run(request.task)
    return {"result": result}