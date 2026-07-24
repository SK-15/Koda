import asyncio
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

from agent.graph import get_compiled_graph
from infra.auth import COOKIE_NAME, decode_session_token
from infra.langfuse_client import build_trace_config
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


def _chunk_text(chunk) -> str:
    """Pull user-facing text from a streamed chat-model chunk.

    Tool-call arguments arrive as tool_call_chunks (not content text), so this
    naturally excludes partial tool JSON and yields only prose.
    """
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(block.get("text", ""))
            elif isinstance(block, str):
                out.append(block)
        return "".join(out)
    return ""


def _token_delta(event: dict) -> str | None:
    """Token text to forward for a graph event, or None to skip it.

    Only the `agent` node's streamed tokens are surfaced — planner (structured
    JSON) and summarize (internal) tokens are not user-facing.
    """
    if event.get("event") != "on_chat_model_stream":
        return None
    if (event.get("metadata") or {}).get("langgraph_node") != "agent":
        return None
    return _chunk_text(event["data"]["chunk"]) or None


async def _pump(graph, inp, config, send):
    """Run the graph to its next stop, streaming agent token deltas as it goes."""
    async for event in graph.astream_events(inp, config=config, version="v2"):
        delta = _token_delta(event)
        if delta:
            await send({"type": "token", "delta": delta})


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


def _approval_payload(values: dict) -> dict:
    """Describe what the paused graph is waiting on, for the client to decide."""
    awaiting_plan = values.get("plan") is not None and values.get("plan_approved") is None
    if awaiting_plan:
        return {"kind": "plan", "plan": values.get("plan")}
    last = values["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    return {
        "kind": "tool",
        "tool_calls": [{"tool": c["name"], "args": c["args"]} for c in calls],
    }


async def _resolve_pause(graph, config, values: dict, decision: dict) -> None:
    """Apply the client's approve/reject decision to the paused graph."""
    awaiting_plan = values.get("plan") is not None and values.get("plan_approved") is None
    approved = bool(decision.get("approved"))
    if awaiting_plan:
        update = {"plan_approved": approved, "awaiting_approval": False}
        if decision.get("plan") is not None:
            update["plan"] = decision["plan"]
        await graph.aupdate_state(config, update)
    else:
        await graph.aupdate_state(config, {"approved": approved, "awaiting_approval": False})


async def _drive_run(frame, backend, capabilities, org_id, user_id, send, bridge, thread_id):
    config = {
        "configurable": {"thread_id": thread_id, "backend": backend},
        **build_trace_config(user_id, thread_id, org_id),
    }
    graph = get_compiled_graph()
    try:
        # Reuse the thread across messages on this connection so the checkpointer
        # preserves conversation history. On a continued turn, append to prior
        # messages; on the first, seed full state.
        snapshot = await graph.aget_state(config)
        if snapshot.values.get("messages"):
            inp = {
                "messages": snapshot.values["messages"] + [HumanMessage(content=frame["message"])],
                "iterations": 0,
                "last_error": None,
                "plan": None,
                "plan_approved": None,
                "plan_mode": frame.get("plan_mode", False),
                "current_step": 0,
                "approved": None,
                "awaiting_approval": False,
            }
        else:
            inp = _build_state(frame, backend.available_tools(), thread_id, org_id, user_id)
        await _pump(graph, inp, config, send)

        # The graph pauses (interrupt_before) at the human gate or plan review.
        # Surface each pause to the client, apply the decision, and resume.
        while True:
            snapshot = await graph.aget_state(config)
            if not snapshot.next:
                break
            decision = await bridge.request_approval(_approval_payload(snapshot.values))
            await _resolve_pause(graph, config, snapshot.values, decision)
            await _pump(graph, None, config, send)

        final = (await graph.aget_state(config)).values
        await send({
            "type": "done",
            "thread_id": thread_id,
            "result": _extract_text(final["messages"][-1].content),
            "cost_usd": final.get("cost_usd"),
        })
    except Exception as e:  # noqa: BLE001 - surface to client
        logger.error("WS RUN ERROR  thread=%s  error=%s", thread_id, e, exc_info=True)
        await send({"type": "error", "thread_id": thread_id, "error": str(e)})


@router.websocket("/ws/run")
async def ws_run(websocket: WebSocket):
    """Interactive run over a duplex socket. The client owns the workspace.

    Protocol:
      client -> {type: hello, capabilities: [...], thread_id?}
      server -> {type: ready, thread_id}
      client -> {type: message, message: "...", plan_mode?, model?, ...}
      server -> {type: token, delta}   (streamed agent text, before done)
      server -> {type: tool_request, call_id, tool, args}
      client -> {type: tool_result, call_id, result}  |  {type: tool_error, call_id, error}
      server -> {type: approval_request, kind: "tool"|"plan", tool_calls?|plan?}
      client -> {type: approval, approved: bool, plan?: [...]}
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

    user_id = decode_session_token(websocket.cookies.get(COOKIE_NAME))
    if not user_id:
        await send({"type": "error", "error": "not authenticated"})
        await websocket.close(code=4401)
        return
    org_id = user_id

    bridge = WsToolBridge(send)
    run_task: asyncio.Task | None = None

    try:
        hello = await websocket.receive_json()
        if hello.get("type") != "hello":
            await send({"type": "error", "error": "expected hello frame first"})
            await websocket.close()
            return
        capabilities = hello.get("capabilities", [])
        backend = ClientProxyBackend(bridge.request_tool, capabilities)

        # One thread per connection (reused across messages for chat continuity).
        # The client may pass thread_id to resume an existing chat.
        thread_id = hello.get("thread_id") or f"{org_id}:{user_id}:{uuid.uuid4()}"
        await send({"type": "ready", "thread_id": thread_id})

        while True:
            frame = await websocket.receive_json()
            ftype = frame.get("type")

            if ftype in ("tool_result", "tool_error"):
                bridge.resolve(frame)
            elif ftype == "approval":
                bridge.resolve_approval(frame)
            elif ftype == "message":
                if run_task and not run_task.done():
                    await send({"type": "error", "error": "a run is already in progress"})
                    continue
                run_task = asyncio.create_task(
                    _drive_run(frame, backend, capabilities, org_id, user_id, send, bridge, thread_id)
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
