async def plan_review_node(state: dict) -> dict:
    if state.get("plan_approved") is True:
        return {"awaiting_approval": False}
    return {"awaiting_approval": True}