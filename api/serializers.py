from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage


def serialize_messages(messages: list) -> list[dict]:
    role_map = {
        HumanMessage: "user",
        AIMessage: "assistant",
        SystemMessage: "system",
        ToolMessage: "tool",
    }
    result = []
    for m in messages:
        role = role_map.get(type(m), "unknown")
        content = m.content if isinstance(m.content, str) else str(m.content)
        result.append({"role": role, "content": content})
    return result
