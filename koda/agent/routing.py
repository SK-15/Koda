from tools.registry import get_tool

def should_continue(state: dict) -> str:
    if state['iterations'] >= state['max_iterations']:
        return "end"
    if state['cost_usd'] >= state['budget_limit_usd']:
        return "end"
    
    last = state['messages'][-1]

    if not hasattr(last, "tool_calls") or not last.tool_calls:
        return "end"
    
    tool_name = last.tool_calls[0]["name"]
    tool = get_tool(tool_name)

    if tool and tool.requires_approval and not state.get("approved"):
        return "human"
    
    return "tools"

def should_summarize(state: dict) -> bool:
    total_words = sum(len(str(m.content).split()) for m in state['messages'])
    total_tokens = total_words / 0.75
    return "summarize" if total_tokens > 16000 else "agent"