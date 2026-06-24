from langchain_core.messages import AIMessage, SystemMessage
from llm.router import get_llm
from llm.cost_tracker import record_usage

def build_system_prompt(state: dict) -> str:
    workspace = state.get("workspace_path", "unknown")
    parts = [
        "You are KODA, an AI coding agent. You read, write, and reason about codebases.",
        f"Your current workspace is: {workspace}",
        "All file paths you use with tools must be relative to the workspace root (not absolute).",
        "Before answering, always explore the workspace first using the glob tool (pattern='**/*') to discover what files exist.",
        "When asked to modify or add code: read the file first, then use file_write to write the complete updated file. Do NOT just describe what you would do — actually do it using tools.",
        "Use tools to gather information before drawing conclusions. Think step by step. Be precise.",
    ]

    if state.get("summary"):
        parts.append(f"\n## Conversation Summary\n{state['summary']}")
    if state.get("memory_index"):
        parts.append(f"\n## Memory Index\n{state['memory_index']}")
    if state.get("last_error"):
        parts.append(f"\n## Last Error (adapt your strategy)\n{state['last_error']}")
    if state.get("plan"):
          current = state.get("current_step", 0)
          lines = ["\n## Plan (approved — execute in order)"]
          for i, step in enumerate(state["plan"]):
              mark = {"done": "x", "skipped": "-", "pending": " "}.get(step.get("status"), " ")
              pointer = "  <-- current step" if i == current else ""
              lines.append(f"- [{mark}] {step['id']}. {step['description']}{pointer}")
          parts.append("\n".join(lines))
    

    return "\n".join(parts)

async def agent_node(state: dict) -> str:
    iterations = state['iterations'] + 1

    if iterations > state['max_iterations']:
        return {
            "iterations" : iterations,
            "messages" : state['messages'] + [AIMessage(content="Reached max iterations. Stopping execution.")]
        }
    
    if state['cost_usd'] >= state['budget_limit_usd']:
        return {
            "iterations" : iterations,
            "messages" : state['messages'] + [AIMessage(content=f"Budget limit ${state['budget_limit_usd']} reached. Stopping execution.")]
        }
    
    system_prompt = build_system_prompt(state)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    llm = get_llm(model=state.get("model"))
    response = await llm.ainvoke(messages)

    input_tokens = response.usage_metadata.get("input_tokens", 0)
    output_tokens = response.usage_metadata.get("output_tokens", 0)

    cost = await record_usage(
        thread_id=state["thread_id"],
        org_id=state["org_id"],
        user_id=state["user_id"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        last_message=str(response.content)[:500],
    )

    return {
        "iterations": iterations,
        "messages": state["messages"] + [response],
        "last_error": None,
        "tokens_used": state["tokens_used"] + input_tokens + output_tokens,
        "cost_usd": state["cost_usd"] + cost,
    }