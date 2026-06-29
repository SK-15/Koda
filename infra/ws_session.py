import asyncio


class WsToolBridge:
    """Correlates server->client tool requests with the client's replies.

    The agent run and the socket reader loop run concurrently. When the agent
    calls a tool, `request_tool` sends a `tool_request` frame and parks a future
    keyed by a call id; the reader loop calls `resolve` when the matching
    `tool_result` / `tool_error` frame arrives, unblocking the run.

    `request_tool` is exactly the transport `ClientProxyBackend` expects, so:
        backend = ClientProxyBackend(bridge.request_tool, capabilities)

    Transport-agnostic: `send` is any async callable taking a JSON-able dict,
    which keeps this independent of (and testable without) FastAPI/WebSocket.
    """

    def __init__(self, send):
        self._send = send            # async fn(dict) -> None
        self._pending: dict = {}     # call_id -> asyncio.Future
        self._counter = 0

    async def request_tool(self, tool_name: str, tool_args: dict) -> str:
        self._counter += 1
        call_id = f"tc-{self._counter}"
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[call_id] = fut
        await self._send({
            "type": "tool_request",
            "call_id": call_id,
            "tool": tool_name,
            "args": tool_args,
        })
        return await fut

    def resolve(self, frame: dict) -> bool:
        """Resolve a parked tool call from a client reply frame.

        Returns True if a pending call matched, False otherwise (unknown or
        already-resolved call id).
        """
        call_id = frame.get("call_id")
        fut = self._pending.pop(call_id, None)
        if fut is None or fut.done():
            return False
        if frame.get("type") == "tool_error":
            fut.set_result(f"Error: {frame.get('error', 'tool failed on client')}")
        else:
            fut.set_result(frame.get("result", ""))
        return True

    def fail_all(self, exc: Exception) -> None:
        """Fail every parked call (e.g. on disconnect) so the run unwinds."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
