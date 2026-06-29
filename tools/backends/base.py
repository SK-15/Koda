from abc import ABC, abstractmethod


class WorkspaceBackend(ABC):
    """Where a tool call actually runs.

    The agent (loop, LLM, planning) is identical across deployments. What
    changes per session is *where* file/exec tool calls land:

    - LocalFsBackend  -> koda's own disk (autonomous / co-located runs)
    - ClientProxyBackend -> proxied over a live connection to the client that
      owns the workspace (terminal client = local disk, browser client =
      in-browser virtual FS). koda never touches its own disk.

    A backend is a live, per-session object. It is NOT part of AgentState
    (state is checkpointed to Redis; a live connection is not serializable).
    It is passed through the graph via config["configurable"]["backend"].
    """

    kind: str = "base"

    @abstractmethod
    async def dispatch(self, tool_name: str, tool_args: dict, state: dict) -> str:
        """Execute one tool call and return its result as a string.

        Implementations own input validation and sandboxing for their
        environment. Raised exceptions are caught by the tool node and surfaced
        to the model as an error result (and counted toward the retry budget).
        """
        ...

    @abstractmethod
    def available_tools(self) -> list[str]:
        """Tool names this backend can service.

        Drives capability negotiation: only these tools should be bound to the
        LLM for the session. A backend that advertises nothing yields a
        pure-chat agent (no file tools).
        """
        ...
