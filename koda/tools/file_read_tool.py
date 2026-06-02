from pathlib import Path
from pydantic import BaseModel
from tools.base import BaseTool, ToolInput, trim_tool_output

class FilereadInput(BaseModel):
    path: str
    offset: int = 0
    limit: int = 2000

class FileReadTool(BaseTool):
    name = "file_read"
    description = "Read a file from the workspace. Returns file contents trimmed to 2000 tokens"
    risk_level = "low"

    def validate_input(self, input: FilereadInput, workspace_path: str) -> bool:
        resolved = Path(workspace_path).joinpath(input.path).resolve()
        return str(resolved).startswith(str(Path(workspace_path).resolve()))
    
    async def execute(self, input: FilereadInput, state: dict) -> str:
        workspace_path = state["workspace_path"]

        if not self.validate_input(input, workspace_path):
            return "Error : path outside workspace"
        
        full_path = Path(workspace_path) / (input.path)

        if not full_path.exists():
            return f"Error : file not found - {input.path}"
        
        if not full_path.is_file():
            return f"Error : not a file - {input.path}"
        
        lines = full_path.read_text(errors="replace").splitlines()
        sliced = lines[input.offset : input.offset + input.limit]
        content = "\n".join(sliced)

        return trim_tool_output(content, max_tokens=2000)