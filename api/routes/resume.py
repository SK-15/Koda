from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from agent.graph import get_compiled_graph
from api.deps import get_identity

router = APIRouter()


class ResumeRequest(BaseModel):
    approved: bool
    plan: list[dict] | None = None


class ResumeResponse(BaseModel):
    thread_id: str
    status: str


@router.post("/resume/{thread_id}", response_model=ResumeResponse)
async def resume(
    thread_id: str,
    request: ResumeRequest,
    identity: tuple = Depends(get_identity),
):
    graph = get_compiled_graph()
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = await graph.aget_state(config)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Thread not found")

    values = snapshot.values
    awaiting_plan = values.get("plan") is not None and values.get("plan_approved") is None

    if awaiting_plan:
        update = {"plan_approved": request.approved, "awaiting_approval": False}
        if request.plan is not None:
            update["plan"] = request.plan
        await graph.aupdate_state(config, update)
    else:
        await graph.aupdate_state(
            config,
            {"approved": request.approved, "awaiting_approval": False},
        )

    if request.approved:
        await graph.ainvoke(None, config=config)

    return ResumeResponse(
        thread_id=thread_id,
        status="resumed" if request.approved else "rejected",
    )