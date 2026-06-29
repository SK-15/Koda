from langchain_core.messages import HumanMessage


async def build_invoke_input(
    snapshot,
    message: str,
    plan_mode: bool,
    budget_limit_usd: float,
    max_iterations: int,
    model: str | None,
    project,
    org_id: str,
    user_id: str,
    chat_id: str,
) -> dict:
    is_first_turn = snapshot is None or not snapshot.values.get("messages")

    if is_first_turn:
        return {
            "messages": [HumanMessage(content=message)],
            "summary": "",
            "iterations": 0,
            "max_iterations": max_iterations,
            "tool_attempts": {},
            "last_error": None,
            "approved": None,
            "awaiting_approval": False,
            "plan": None,
            "plan_approved": None,
            "plan_mode": plan_mode,
            "current_step": 0,
            "memory_index": "",
            "workspace_path": project.workspace_path,
            "enabled_tools": getattr(project, "capabilities", None),
            "backend_kind": "local",
            "org_id": org_id,
            "user_id": user_id,
            "thread_id": chat_id,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "budget_limit_usd": budget_limit_usd,
            "model": model,
        }

    prior = snapshot.values.get("messages", [])
    return {
        "messages": prior + [HumanMessage(content=message)],
        "iterations": 0,
        "last_error": None,
        "plan": None,
        "plan_approved": None,
        "plan_mode": plan_mode,
        "current_step": 0,
        "approved": None,
        "awaiting_approval": False,
        "budget_limit_usd": budget_limit_usd,
        "max_iterations": max_iterations,
        "model": model,
    }
