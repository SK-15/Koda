import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_identity
from api.chat_runner import build_invoke_input
from api.serializers import serialize_messages
from infra.postgres import get_db
from infra import projects_repo, chats_repo
from infra.task_store import set_task_status
from agent.graph import get_compiled_graph

router = APIRouter()


class SendMessageRequest(BaseModel):
    message: str
    plan_mode: bool = False
    budget_limit_usd: float = 2.0
    max_iterations: int = 20
    model: str | None = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v):
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


async def _run_chat(task_id: str, chat_id: str, invoke_input: dict):
    await set_task_status(task_id, "running")
    try:
        config = {"configurable": {"thread_id": chat_id}}
        result = await get_compiled_graph().ainvoke(invoke_input, config=config)
        last = result["messages"][-1]
        content = last.content
        if isinstance(content, list):
            content = " ".join(
                block["text"] if isinstance(block, dict) else str(block)
                for block in content
                if not isinstance(block, dict) or block.get("type") != "tool_use"
            )
        await set_task_status(task_id, "success", str(content))
    except Exception as e:
        await set_task_status(task_id, "failed", str(e))


@router.post("/chats")
async def create_chat_default(
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    project = await projects_repo.get_or_create_default(db, org_id, user_id)
    chat = await chats_repo.create_chat(db, project.project_id, org_id, user_id)
    return {
        "chat_id": chat.thread_id,
        "project_id": chat.project_id,
        "title": chat.title,
        "created_at": chat.created_at,
    }


@router.post("/projects/{project_id}/chats")
async def create_chat(
    project_id: str,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    project = await projects_repo.get_project(db, project_id, org_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    chat = await chats_repo.create_chat(db, project_id, org_id, user_id)
    return {
        "chat_id": chat.thread_id,
        "project_id": chat.project_id,
        "title": chat.title,
        "created_at": chat.created_at,
    }


@router.get("/chats")
async def list_my_chats(
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    chats = await chats_repo.list_all_chats(db, org_id, user_id)
    return [
        {
            "chat_id": c.thread_id,
            "title": c.title,
            "last_message": c.last_message,
            "updated_at": c.updated_at,
            "cost_usd": c.cost_usd,
        }
        for c in chats
    ]


@router.get("/projects/{project_id}/chats")
async def list_chats(
    project_id: str,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    project = await projects_repo.get_project(db, project_id, org_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    chats = await chats_repo.list_chats(db, project_id, org_id, user_id)
    return [
        {
            "chat_id": c.thread_id,
            "title": c.title,
            "last_message": c.last_message,
            "updated_at": c.updated_at,
            "cost_usd": c.cost_usd,
        }
        for c in chats
    ]


@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    chat = await chats_repo.get_chat(db, chat_id, org_id, user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    config = {"configurable": {"thread_id": chat_id}}
    snapshot = await get_compiled_graph().aget_state(config)
    messages = []
    if snapshot and snapshot.values.get("messages"):
        messages = serialize_messages(snapshot.values["messages"])

    return {
        "chat_id": chat.thread_id,
        "title": chat.title,
        "messages": messages,
    }


@router.post("/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    identity: tuple = Depends(get_identity),
    db: AsyncSession = Depends(get_db),
):
    org_id, user_id = identity
    chat = await chats_repo.get_chat(db, chat_id, org_id, user_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    project = await projects_repo.get_project(db, chat.project_id, org_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    config = {"configurable": {"thread_id": chat_id}}
    snapshot = await get_compiled_graph().aget_state(config)

    invoke_input = await build_invoke_input(
        snapshot=snapshot,
        message=body.message,
        plan_mode=body.plan_mode,
        budget_limit_usd=body.budget_limit_usd,
        max_iterations=body.max_iterations,
        model=body.model,
        project=project,
        org_id=org_id,
        user_id=user_id,
        chat_id=chat_id,
    )

    task_id = str(uuid.uuid4())
    await set_task_status(task_id, "queued")
    background_tasks.add_task(_run_chat, task_id, chat_id, invoke_input)

    await chats_repo.update_chat_meta(
        db,
        chat_id,
        last_message=body.message,
        title=body.message if chat.title is None else None,
    )

    return {"chat_id": chat_id, "task_id": task_id, "status": "queued"}
