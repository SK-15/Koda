from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from llm.router import get_llm

SUMMARIZE_PROMPT = """Summarize the conversation below into 3-5 sentences.
  Focus on: what was asked, what was found, what was changed, what is still pending.
  Be precise. No filler.

  Conversation:
  {messages}
  """

async def summarize_node(state: dict) -> dict:
    messages = state['messages']

    to_summarize = messages[:-4]
    keep_messages = messages[-4:]

    conversation_text = "\n".join(f"{type(msg).__name__}: {msg.content}" for msg in to_summarize)

    llm = get_llm()
    response = await llm.ainvoke([
        HumanMessage(content=SUMMARIZE_PROMPT.format(messages=conversation_text))
    ])

    existing_summary = state.get("summary", "")
    if existing_summary:
        new_summary = existing_summary + "\n\n" + response.content
    else:
        new_summary = response.content

    return {
        "messages" : keep_messages,
        "summary" : new_summary
    }  