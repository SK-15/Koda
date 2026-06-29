import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

from agent.graph import get_compiled_graph
from infra.ws_session import WsToolBridge
from tools.backends import ClientProxyBackend

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_text(content) -> str:
    if isinstance(content, list):
        return " ".join(
            block["text"] if isinstance(block, dict) else str(block)
            for block in content
            if not isinstance(block, dict) or block.get("type") != "tool_use"
        )
    return str(content)


def _build_state(frame: dict, capabilities: list[str], thread_id: str,
                 org_id: str, user_id: str) -> dict:
    return {
        "messages": [HumanMessage(content=frame["message"])],
        "summary": "",
        "iterations": 0,
        "max_iterations": frame.get("max_iterations", 20),
        "tool_attempts": {},
        "last_error": None,
        "approved": None,
        "awaiting_approval": False,
        "memory_index": "",
        # workspace lives on the client; this is only a label for the prompt.
        "workspace_path": frame.get("workspace_label", "client workspace"),
        "org_id": org_id,
        "user_id": user_id,
        "thread_id": thread_id,
        "tokens_used": 0,
        "cost_usd": 0.0,
        "budget_limit_usd": frame.get("budget_limit_usd", 2.0),
        "model": frame.get("model"),
        "plan": None,
        "plan_approved": None,
        "plan_mode": frame.get("plan_mode", False),
        "current_step": 0,
        "enabled_tools": capabilities,
        "backend_kind": "proxy",
    }


async def _drive_run(frame, backend, capabilities, org_id, user_id, send):
    thread_id = f"{org_id}:{user_id}:{uuid.uuid4()}"
    state = _build_state(frame, capabilities, thread_id, org_id, user_id)
    config = {"configurable": {"thread_id": thread_id, "backend": backend}}
    try:
        result = await get_compiled_graph().ainvoke(state, config=config)
        await send({
            "type": "done",
            "thread_id": thread_id,
            "result": _extract_text(result["messages"][-1].content),
            "cost_usd": result.get("cost_usd"),
        })
    except Exception as e:  # noqa: BLE001 - surface to client
        logger.error("WS RUN ERROR  thread=%s  error=%s", thread_id, e, exc_info=True)
        await send({"type": "error", "thread_id": thread_id, "error": str(e)})


@router.websocket("/ws/run")
async def ws_run(websocket: WebSocket):
    """Interactive run over a duplex socket. The client owns the workspace.

    Protocol:
      client -> {type: hello, capabilities: [...], org_id?, user_id?}
      client -> {type: message, message: "...", plan_mode?, model?, ...}
      server -> {type: tool_request, call_id, tool, args}
      client -> {type: tool_result, call_id, result}  |  {type: tool_error, call_id, error}
      server -> {type: done, thread_id, result, cost_usd}  |  {type: error, ...}
      client -> {type: close}

    The run is driven on a background task so the receive loop keeps delivering
    tool replies while the agent is mid-call.
    """
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(obj: dict):
        async with send_lock:
            await websocket.send_json(obj)

    bridge = WsToolBridge(send)
    run_task: asyncio.Task | None = None

    try:
        hello = await websocket.receive_json()
        if hello.get("type") != "hello":
            await send({"type": "error", "error": "expected hello frame first"})
            await websocket.close()
            return
        capabilities = hello.get("capabilities", [])
        org_id = hello.get("org_id", "default")
        user_id = hello.get("user_id", "default")
        backend = ClientProxyBackend(bridge.request_tool, capabilities)

        while True:
            frame = await websocket.receive_json()
            ftype = frame.get("type")

            if ftype in ("tool_result", "tool_error"):
                bridge.resolve(frame)
            elif ftype == "message":
                if run_task and not run_task.done():
                    await send({"type": "error", "error": "a run is already in progress"})
                    continue
                run_task = asyncio.create_task(
                    _drive_run(frame, backend, capabilities, org_id, user_id, send)
                )
            elif ftype == "close":
                break
            else:
                await send({"type": "error", "error": f"unknown frame type: {ftype}"})

    except WebSocketDisconnect:
        bridge.fail_all(RuntimeError("client disconnected"))
    finally:
        if run_task and not run_task.done():
            run_task.cancel()
