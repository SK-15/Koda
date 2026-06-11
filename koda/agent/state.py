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
    awainting_approval: bool

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

