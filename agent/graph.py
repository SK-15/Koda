from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver


from agent.state import AgentState
from agent.nodes.agent_node import agent_node
from agent.nodes.tool_node import tool_node
from agent.nodes.summarize_node import summarize_node
from agent.nodes.human_node import human_node
from agent.nodes.planner_node import planner_node
from agent.nodes.plan_review_node import plan_review_node
from agent.routing import should_continue, should_summarize, route_entry, route_after_review, route_after_human

def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("human", human_node)
    graph.add_node("planner", planner_node)
    graph.add_node("plan_review", plan_review_node)

    graph.add_conditional_edges(START, route_entry, {"planner":"planner","agent":"agent"})

    graph.add_edge("planner","plan_review")

    graph.add_conditional_edges("plan_review", route_after_review, {"agent":"agent","end":END})

    graph.add_conditional_edges("agent", should_continue,
                               {"tools": "tools",
                                "human": "human",
                                "end": END})

    graph.add_conditional_edges("tools", should_summarize,
                               {"summarize": "summarize",
                                "agent": "agent"})

    graph.add_edge("summarize", "agent")

    graph.add_conditional_edges("human", route_after_human,
                               {"tools": "tools",
                                "end": END})

    if checkpointer is None:
        checkpointer = MemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["plan_review","human"],
    )

compiled_graph = None  # initialized in api/main.py lifespan with Redis checkpointer


def get_compiled_graph():
    if compiled_graph is None:
        return build_graph()
    return compiled_graph

    
