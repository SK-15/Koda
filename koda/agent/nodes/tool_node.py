from langchain_core.messages import ToolMessage
from tools.registry import get_tool

async def tool_node(state: dict) -> dict:
    last_message = state['messages'][-1]
    tool_attempts = dict(state['tool_attempts'])
    messages = list(state['messages'])
    last_error = None

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]

        tool = get_tool(tool_name)

        if tool is None:
            error_msg = f"Unknown tool: '{tool_name}'"
            messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))
            last_error = error_msg
            continue

        tool_attempts[tool_name] = tool_attempts.get(tool_name, 0) + 1

        if tool_attempts[tool_name] > 3:
            error_msg = f"Tool '{tool_name}' failed 3 times. Giving up."
            messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))
            last_error = error_msg
            continue

        try:
            input_model = tool.input_class(**tool_args)
            result = await tool.execute(input_model, state)
            tool_attempts[tool_name] = 0
            messages.append(ToolMessage(content=result, tool_call_id=tool_call_id))
        
        except Exception as e:
            error_msg = f"Error executing tool '{tool_name}': {str(e)}"
            messages.append(ToolMessage(content=error_msg, tool_call_id=tool_call_id))
            last_error = error_msg
        
    return {
        "messages" : messages,
        "tool_attempts" : tool_attempts,
        "last_error" : last_error
    }