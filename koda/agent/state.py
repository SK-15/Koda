from typing import TypedDict

class AgentState(TypedDict):
    """Represents the state of an agent."""
    messages: list
    summary: str

    # Loop guard
    iterations: int
    max_iterations: int

    # Tool tracking
    tool_attempts: dict
    last_error: str | None

    # human in the loop
    approved: bool | None
    awaiting_approval: bool

    #Planning
    plan: list[dict] | None         # [{"id": 1, "description": "...", "status": "pending"}]
    plan_approved: bool | None      # None = not decided, True = execute, False = rejected
    plan_mode: bool                 # per-run flag from RunRequest
    current_step: int               # index into plan (starts at 0)

    # Memory
    memory_index : str
    workspace_path: str

    # Multi-tenancy
    org_id : str
    user_id : str
    thread_id : str

    # Cost tracking
    tokens_used: int
    cost_usd: float
    budget_limit_usd: float

    # LLM selection
    model: str | None

