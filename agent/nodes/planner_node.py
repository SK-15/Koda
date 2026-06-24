from langchain_core.messages import SystemMessage
from llm.router import get_planner_llm

PLANNER_PROMPT = (
    "You are KODA's planner. Break the user's request into an ordered list of "
    "concrete, verifiable steps. Do NOT execute anything and do NOT call any "
    "tools other than producing the plan. Keep steps minimal and in order."
)


async def planner_node(state: dict) -> dict:
    workspace = state.get("workspace_path", "unknown")
    system = SystemMessage(content=f"{PLANNER_PROMPT}\nWorkspace: {workspace}")
    llm = get_planner_llm(model=state.get("model"))
    plan_obj = await llm.ainvoke([system] + state["messages"])

    plan = [
        {"id": i + 1, "description": step.description, "status": "pending"}
        for i, step in enumerate(plan_obj.steps)
    ]
    return {
        "plan": plan,
        "current_step": 0,
        "plan_approved": None,
    }