from agent.graph import build_graph
from langgraph.checkpoint.memory import MemorySaver


WORKER_DEFAULT_TOOLS = {"file_read", "grep", "glob"}
WORKER_ELEVATED_TOOLS = {"file_read", "grep", "glob", "file_write"}


class WorkerAgent:
    def __init__(
        self,
        task: str,
        workspace_path: str,
        thread_id: str,
        allowed_tools: set = None,
        org_id: str = "default",
        user_id: str = "default",
    ):
        self.task = task
        self.thread_id = thread_id
        self.initial_state = {
            "messages": [],
            "summary": "",
            "iterations": 0,
            "max_iterations": 10,
            "tool_attempts": {},
            "last_error": None,
            "approved": None,
            "awaiting_approval": False,
            "memory_index": "",
            "workspace_path": workspace_path,
            "org_id": org_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "budget_limit_usd": 0.50,
        }
        self.allowed_tools = allowed_tools or WORKER_DEFAULT_TOOLS
        self.graph = build_graph(checkpointer=MemorySaver())

    async def run(self) -> str:
        from langchain_core.messages import HumanMessage
        from tools.registry import _REGISTRY

        original_registry = dict(_REGISTRY)
        blocked = {k for k in _REGISTRY if k not in self.allowed_tools}
        for key in blocked:
            del _REGISTRY[key]

        try:
            state = {**self.initial_state, "messages": [HumanMessage(content=self.task)]}
            config = {"configurable": {"thread_id": self.thread_id}}
            result = await self.graph.ainvoke(state, config=config)
            return result["messages"][-1].content
        finally:
            _REGISTRY.update(original_registry)