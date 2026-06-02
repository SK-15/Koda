from langchain_core.messages import AIMessage, SystemMessage
from llm.router import get_llm

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
    
    system_prmpt = build_system_prompt(state)
    messages = [SystemMessage(content=system_prmpt)] + state['messages']
    llm = get_llm()
    response = await llm.ainvoke(messages)

    return {
        "iterations" : iterations,
        "messages" : state['messages'] + [response],
        "last_error" : None
    }