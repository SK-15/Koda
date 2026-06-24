from langchain_core.messages import AIMessage


async def human_node(state: dict) -> dict:
    if state.get("approved") is True:
        return {
            "awaiting_approval": False,
            "approved": None,
        }

    return {
        "awaiting_approval": True,
        "messages": state["messages"] + [
            AIMessage(content="Awaiting human approval to execute bash command.")
        ],
    }