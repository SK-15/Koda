from pydantic import BaseModel
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools.base import BaseTool, trim_tool_output


class McpClientInput(BaseModel):
    server_command: str
    server_args: list[str] = []
    tool_name: str
    tool_args: dict = {}


class McpClientTool(BaseTool):
    name = "mcp_client"
    description = (
        "Connect to an MCP server over stdio (spawns server_command) and call one of its tools. "
        "Requires human approval since it launches an external process."
    )
    risk_level = "high"
    requires_approval = True

    def validate_input(self, input: McpClientInput, workspace_path: str = "") -> bool:
        return bool(input.server_command.strip()) and bool(input.tool_name.strip())

    async def execute(self, input: McpClientInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : server_command and tool_name must not be empty"

        params = StdioServerParameters(command=input.server_command, args=input.server_args)

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(input.tool_name, input.tool_args)
        except Exception as e:
            return f"Error : mcp call failed - {e}"

        parts = []
        for item in result.content:
            text = getattr(item, "text", None)
            parts.append(text if text is not None else str(item))

        output = "\n".join(parts) if parts else "No content returned."
        return trim_tool_output(output, max_tokens=2000)
