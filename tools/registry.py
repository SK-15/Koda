from tools.file_read_tool import FileReadTool, FileReadInput
from tools.file_write_tool import FileWriteTool, FileWriteInput
from tools.grep_tool import GrepTool, GrepInput
from tools.glob_tool import GlobTool, GlobInput
from tools.bash_tool import BashTool, BashInput
from tools.web_search_tool import WebSearchTool, WebSearchInput

_REGISTRY: dict = {}


def _register(tool_instance, input_class):
    tool_instance.input_class = input_class
    _REGISTRY[tool_instance.name] = tool_instance


_register(FileReadTool(), FileReadInput)
_register(FileWriteTool(), FileWriteInput)
_register(GrepTool(), GrepInput)
_register(GlobTool(), GlobInput)
_register(BashTool(), BashInput)
_register(WebSearchTool(), WebSearchInput)


def get_tool(name: str):
    return _REGISTRY.get(name)


def all_tools() -> list:
    return list(_REGISTRY.values())
