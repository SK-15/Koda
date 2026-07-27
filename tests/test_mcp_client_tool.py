import pytest

from tools.mcp_client_tool import McpClientTool, McpClientInput


class FakeContentItem:
    def __init__(self, text):
        self.text = text


class FakeToolResult:
    def __init__(self, content):
        self.content = content


class FakeClientSession:
    def __init__(self, read, write, result=None, raise_exc=None):
        self._result = result
        self._raise_exc = raise_exc
        self.last_call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def initialize(self):
        return None

    async def call_tool(self, tool_name, tool_args):
        self.last_call = (tool_name, tool_args)
        if self._raise_exc:
            raise self._raise_exc
        return self._result


class FakeStdioClient:
    def __init__(self, params):
        self.params = params

    async def __aenter__(self):
        return ("read-stream", "write-stream")

    async def __aexit__(self, *args):
        return False


class TestMcpClientTool:
    def setup_method(self):
        self.tool = McpClientTool()

    def test_tool_metadata(self):
        assert self.tool.name == "mcp_client"
        assert self.tool.risk_level == "high"
        assert self.tool.requires_approval is True

    def test_validate_input_rejects_empty_fields(self):
        assert self.tool.validate_input(
            McpClientInput(server_command="", tool_name="foo"), "/ws"
        ) is False
        assert self.tool.validate_input(
            McpClientInput(server_command="node server.js", tool_name=""), "/ws"
        ) is False

    @pytest.mark.asyncio
    async def test_execute_returns_tool_text(self, monkeypatch):
        import tools.mcp_client_tool as mct

        result = FakeToolResult(content=[FakeContentItem("42")])
        session_holder = {}

        def make_session(read, write):
            session = FakeClientSession(read, write, result=result)
            session_holder["session"] = session
            return session

        monkeypatch.setattr(mct, "stdio_client", lambda params: FakeStdioClient(params))
        monkeypatch.setattr(mct, "ClientSession", make_session)

        output = await self.tool.execute(
            McpClientInput(server_command="node", server_args=["server.js"], tool_name="add", tool_args={"a": 1, "b": 2}),
            {"workspace_path": "/ws"},
        )

        assert output == "42"
        assert session_holder["session"].last_call == ("add", {"a": 1, "b": 2})

    @pytest.mark.asyncio
    async def test_execute_no_content(self, monkeypatch):
        import tools.mcp_client_tool as mct

        result = FakeToolResult(content=[])
        monkeypatch.setattr(mct, "stdio_client", lambda params: FakeStdioClient(params))
        monkeypatch.setattr(mct, "ClientSession", lambda read, write: FakeClientSession(read, write, result=result))

        output = await self.tool.execute(
            McpClientInput(server_command="node", tool_name="noop"),
            {"workspace_path": "/ws"},
        )

        assert output == "No content returned."

    @pytest.mark.asyncio
    async def test_execute_failure(self, monkeypatch):
        import tools.mcp_client_tool as mct

        monkeypatch.setattr(mct, "stdio_client", lambda params: FakeStdioClient(params))
        monkeypatch.setattr(
            mct, "ClientSession",
            lambda read, write: FakeClientSession(read, write, raise_exc=RuntimeError("server crashed")),
        )

        output = await self.tool.execute(
            McpClientInput(server_command="node", tool_name="add"),
            {"workspace_path": "/ws"},
        )

        assert output == "Error : mcp call failed - server crashed"

    @pytest.mark.asyncio
    async def test_execute_invalid_input(self):
        output = await self.tool.execute(
            McpClientInput(server_command="", tool_name=""),
            {"workspace_path": "/ws"},
        )
        assert output == "Error : server_command and tool_name must not be empty"
