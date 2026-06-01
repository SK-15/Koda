from tools.file_read_tool import FileReadTool, FileReadInput
from tools.grep_tool import GrepTool, GrepInput

_REGISTRY: dict = {}

def _registry(tool_instance, input_class):
    tool_instance.input_class = input_class
    _REGISTRY[tool_instance.__class__.__name__] = tool_instance

_register(FileReadTool(), FileReadInput)
_register(GrepTool(), GrepInput)

def get_tool(name: str):
    return _REGISTRY.get(name)

def all_tools() -> list:
    return list(_REGISTRY.values())