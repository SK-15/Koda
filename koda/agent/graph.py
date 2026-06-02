from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agent.state import AgentState
from agent.nodes.agent_node import agent_node
from agent.nodes.tool_node import tool_node
from agent.nodes.summarize_node import summarize_node
from agent.nodes.human_node import human_node
from agent.routing import should_continue, should_summarize

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("human", human_node)

    graph.set_entry_point("agent")

    graph.add_conditional_edges("agent", should_continue,
                               {"tools": "tools",
                                "human": "human",
                                "end": END})

    graph.add_conditional_edges("tools", should_summarize,
                               {"summarize": "summarize",
                                "agent": "agent"})

    graph.add_edge("summarize", "agent")
    graph.add_edge("human", END)

    checkpointer = MemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human"],
    )

compiled_graph = build_graph()

    
