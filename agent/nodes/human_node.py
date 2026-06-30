from langchain_core.messages import AIMessage


async def human_node(state: dict) -> dict:
    # On approve, leave approved=True so route_after_human sends us to the tool
    # node to actually run the pending command. tool_node resets approved to None
    # afterward, so the next risky tool re-gates.
    if state.get("approved") is True:
        return {
            "awaiting_approval": False,
        }

    return {
        "awaiting_approval": True,
        "messages": state["messages"] + [
            AIMessage(content="Awaiting human approval to execute bash command.")
        ],
    }