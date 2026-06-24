from pathlib import Path
from pydantic import BaseModel
from tools.base import BaseTool, trim_tool_output

class GlobInput(BaseModel):
    pattern: str
    path: str = "."

class GlobTool(BaseTool):
    name = "glob"
    description = "List files matching a glob pattern in the workspace. Returns file paths."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: GlobInput, workspace_path: str) -> bool:
        resolved = Path(workspace_path).joinpath(input.path).resolve()
        return str(resolved).startswith(str(Path(workspace_path).resolve()))
    
    async def execute(self, input: GlobInput, state: dict) -> str:
        workspace_path = state["workspace_path"]

        if not self.validate_input(input, workspace_path):
            return "Error : path outside workspace"
        
        search_path = Path(workspace_path) / input.path
        matches = sorted(search_path.glob(input.pattern))

        if not matches:
            return f"No files found matching pattern '{input.pattern}'"
        
        lines = [str(p.relative_to(workspace_path)) for p in matches]
        output = "\n".join(lines)
        return trim_tool_output(output, max_tokens=500)