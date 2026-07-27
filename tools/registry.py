from tools.file_read_tool import FileReadTool, FileReadInput
from tools.file_write_tool import FileWriteTool, FileWriteInput
from tools.grep_tool import GrepTool, GrepInput
from tools.glob_tool import GlobTool, GlobInput
from tools.bash_tool import BashTool, BashInput
from tools.web_search_tool import WebSearchTool, WebSearchInput
from tools.web_fetch_tool import WebFetchTool, WebFetchInput
from tools.http_request_tool import HttpRequestTool, HttpRequestInput
from tools.git_tool import GitTool, GitInput
from tools.code_exec_tool import CodeExecTool, CodeExecInput
from tools.memory_search_tool import MemorySearchTool, MemorySearchInput
from tools.vision_describe_tool import VisionDescribeTool, VisionDescribeInput
from tools.mcp_client_tool import McpClientTool, McpClientInput
from tools.structured_output_validator_tool import (
    StructuredOutputValidatorTool,
    StructuredOutputValidatorInput,
)

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
_register(WebFetchTool(), WebFetchInput)
_register(HttpRequestTool(), HttpRequestInput)
_register(GitTool(), GitInput)
_register(CodeExecTool(), CodeExecInput)
_register(MemorySearchTool(), MemorySearchInput)
_register(VisionDescribeTool(), VisionDescribeInput)
_register(McpClientTool(), McpClientInput)
_register(StructuredOutputValidatorTool(), StructuredOutputValidatorInput)


def get_tool(name: str):
    return _REGISTRY.get(name)


def all_tools() -> list:
    return list(_REGISTRY.values())
