import uuid
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from agent.graph import compiled_graph
from infra.task_store import set_task_status

router = APIRouter()


class RunRequest(BaseModel):
    message: str
    workspace_path: str
    org_id: str = "default"
    user_id: str = "default"
    budget_limit_usd: float = 2.00
    max_iterations: int = 20
    model: str | None = None


class RunResponse(BaseModel):
    thread_id: str
    task_id: str
    status: str


async def _run_graph(task_id: str, thread_id: str, initial_state: dict):
    await set_task_status(task_id, "running")
    try:
        config = {"configurable": {"thread_id": thread_id}}
        result = await compiled_graph.ainvoke(initial_state, config=config)
        last_message = result["messages"][-1]
        await set_task_status(task_id, "success", last_message.content)
    except Exception as e:
        await set_task_status(task_id, "failed", str(e))


@router.post("/run", response_model=RunResponse)
async def run(request: RunRequest, background_tasks: BackgroundTasks):
    thread_id = f"{request.org_id}:{request.user_id}:{uuid.uuid4()}"
    task_id = str(uuid.uuid4())

    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "summary": "",
        "iterations": 0,
        "max_iterations": request.max_iterations,
        "tool_attempts": {},
        "last_error": None,
        "approved": None,
        "awaiting_approval": False,
        "memory_index": "",
        "workspace_path": request.workspace_path,
        "org_id": request.org_id,
        "user_id": request.user_id,
        "thread_id": thread_id,
        "tokens_used": 0,
        "cost_usd": 0.0,
        "budget_limit_usd": request.budget_limit_usd,
        "model": request.model,
    }

    await set_task_status(task_id, "queued")
    background_tasks.add_task(_run_graph, task_id, thread_id, initial_state)

    return RunResponse(thread_id=thread_id, task_id=task_id, status="queued")
