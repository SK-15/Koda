from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage


def _serialize_ai_content(m: AIMessage):
    """Normalize an AIMessage's content for the frontend's block parser.

    Anthropic's native tool use embeds `tool_use` blocks directly in
    `.content` (a list of dicts) — the frontend's parser (a hand-rolled
    Python-literal reader, see koda-app's src/parse.ts) already expects
    `str()` of exactly that shape.

    Other providers (and LangChain's general normalization) instead leave
    `.content` as plain text — often empty — and put the call in the
    separate `.tool_calls` list. Left alone, that silently drops every tool
    call from persisted history (the UI's canvas/file reconstruction reads
    only `.content`). So when `.tool_calls` is present and not already
    reflected in `.content`, fold it into the same block-list shape before
    stringifying.
    """
    if isinstance(m.content, list):
        return str(m.content)

    tool_calls = getattr(m, "tool_calls", None)
    if not tool_calls:
        return m.content if isinstance(m.content, str) else str(m.content)

    blocks = []
    if m.content:
        blocks.append({"type": "text", "text": m.content})
    for tc in tool_calls:
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id"),
            "name": tc.get("name"),
            "input": tc.get("args", {}),
        })
    return str(blocks)


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
        if isinstance(m, AIMessage):
            content = _serialize_ai_content(m)
        else:
            content = m.content if isinstance(m.content, str) else str(m.content)
        result.append({"role": role, "content": content})
    return result
