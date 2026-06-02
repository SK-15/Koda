from langchain_core.messages import AIMessage, SystemMessage
from llm.router import get_llm
from llm.cost_tracker import record_usage

def build_system_prompt(state: dict) -> str:

    parts = [
        "You are KODA, an AI code agent, You read, write and reasone about codebase.",
        "Use tools to gather informatopn before making changes",
        "Think step bu step. Be prcise."
    ]

    if state.get("summary"):
        parts.append(f"\n## COnversation summary\n{state['summary']}")
    if state.get("memory_index"):
        parts.append(f"\n## Memory Index\n{state['memory_index']}")
    if state.get("last_error"):
        parts.append(f"\n## LastError (adapt your startegy)\n{state['last_error']}")
    
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
    llm = get_llm()
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