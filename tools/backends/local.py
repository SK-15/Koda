from tools.backends.base import WorkspaceBackend
from tools.registry import get_tool, all_tools


class LocalFsBackend(WorkspaceBackend):
    """Runs tool calls in-process against koda's own filesystem.

    This preserves the original behavior: each call is modelled with the
    registered tool's input class and executed by the tool itself (path
    validation + Docker sandbox for bash all live in the tool). Used for
    autonomous / co-located runs where koda has the files.
    """

    kind = "local"

    async def dispatch(self, tool_name: str, tool_args: dict, state: dict) -> str:
        tool = get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: '{tool_name}'")
        input_model = tool.input_class(**tool_args)
        return await tool.execute(input_model, state)

    def available_tools(self) -> list[str]:
        return [t.name for t in all_tools()]
