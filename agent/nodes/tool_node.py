import logging
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from tools.backends import resolve_backend

logger = logging.getLogger(__name__)

async def tool_node(state: dict, config: RunnableConfig | None = None) -> dict:
    last_message = state['messages'][-1]
    tool_attempts = dict(state['tool_attempts'])
    messages = list(state['messages'])
    last_error = None

    backend = resolve_backend(state, config)
    available = set(backend.available_tools())

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]

        logger.info("TOOL CALL  name=%s  args=%s  backend=%s  workspace=%s", tool_name, tool_args, backend.kind, state.get("workspace_path"))

        if tool_name not in available:
            error_msg = f"Unknown tool: '{tool_name}'"
            logger.warning("TOOL NOT FOUND  name=%s  backend=%s", tool_name, backend.kind)
            messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))
            last_error = error_msg
            continue

        tool_attempts[tool_name] = tool_attempts.get(tool_name, 0) + 1

        if tool_attempts[tool_name] > 3:
            error_msg = f"Tool '{tool_name}' failed 3 times. Giving up."
            logger.warning("TOOL MAX RETRIES  name=%s", tool_name)
            messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))
            last_error = error_msg
            continue

        try:
            result = await backend.dispatch(tool_name, tool_args, state)
            tool_attempts[tool_name] = 0
            logger.info("TOOL RESULT  name=%s  result=%s", tool_name, result[:200] if isinstance(result, str) else result)
            messages.append(ToolMessage(content=result, tool_call_id=tool_call_id))

        except Exception as e:
            error_msg = f"Error executing tool '{tool_name}': {str(e)}"
            logger.error("TOOL ERROR  name=%s  error=%s", tool_name, e, exc_info=True)
            messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))
            last_error = error_msg

    return {
        "messages": messages,
        "tool_attempts": tool_attempts,
        "last_error": last_error,
    }
