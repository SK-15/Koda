from typing import Awaitable, Callable

from tools.backends.base import WorkspaceBackend
from tools.registry import get_tool

# A transport: given (tool_name, tool_args) sends the request to the client that
# owns the workspace and resolves with the client's result string. The WS
# handler supplies this; it is the only thing that knows about the socket.
ToolRequestFn = Callable[[str, dict], Awaitable[str]]

# Tools that must always run on koda's own server, regardless of which
# client is connected, because they need server-held secrets (API keys)
# the client never has.
SERVER_SIDE_TOOLS = {"web_search"}


class ClientProxyBackend(WorkspaceBackend):
    """Proxies every tool call to the client that owns the workspace.

    koda holds no files. When the agent calls a tool, the call is serialized
    and sent to the client over a live connection; the client executes it
    against its own environment (terminal -> local disk + shell, browser ->
    in-browser virtual FS) and returns the result.

    Tools in SERVER_SIDE_TOOLS are the exception: they run in-process here
    instead, since they depend on secrets only the server holds.

    Transport is injected as `request_fn` so this class stays independent of
    the WebSocket layer (and unit-testable with a fake). `capabilities` is the
    set of tools the client advertised it can service on connect.
    """

    kind = "proxy"

    def __init__(self, request_fn: ToolRequestFn, capabilities: list[str]):
        self._request_fn = request_fn
        self._capabilities = list(capabilities)

    async def dispatch(self, tool_name: str, tool_args: dict, state: dict) -> str:
        if tool_name in SERVER_SIDE_TOOLS:
            tool = get_tool(tool_name)
            input_model = tool.input_class(**tool_args)
            return await tool.execute(input_model, state)

        if tool_name not in self._capabilities:
            raise ValueError(
                f"Client does not support tool '{tool_name}' "
                f"(advertised: {self._capabilities})"
            )
        return await self._request_fn(tool_name, tool_args)

    def available_tools(self) -> list[str]:
        return list(set(self._capabilities) | SERVER_SIDE_TOOLS)
