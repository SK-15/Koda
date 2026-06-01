from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from agent.graph import compiled_graph

router = APIRouter()


class ResumeRequest(BaseModel):
    approved: bool


class ResumeResponse(BaseModel):
    thread_id: str
    status: str


@router.post("/resume/{thread_id}", response_model=ResumeResponse)
async def resume(thread_id: str, request: ResumeRequest):
    config = {"configurable": {"thread_id": thread_id}}

    state = await compiled_graph.aget_state(config)
    if not state:
        raise HTTPException(status_code=404, detail="Thread not found")

    await compiled_graph.aupdate_state(
        config,
        {"approved": request.approved, "awaiting_approval": False},
    )

    if request.approved:
        await compiled_graph.ainvoke(None, config=config)

    return ResumeResponse(
        thread_id=thread_id,
        status="resumed" if request.approved else "rejected",
    )