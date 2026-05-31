import subprocess
from pahtlib import Path
from pydantic import BaseModel
from tools.base import BaseTool, trim_tool_output

class GrepInput(BaseModel):
    pattern: str
    path: str = "."
    file_pattern: str = "."
    case_sensitive: bool = True
    max_results: int = 50

class GrepTool(BaseTool):
    name = "grep"
    description = "Search for a pattern across files in workspace. Reuturns the matching lines with file:line context"
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: GrepInput, workspace_path: str) -> str:
        resolved = Path(workspace_path).joinpath(input.path).resolve()
        return str(resolved).startswith(str(Path(workspace_path).resolve()))
    
    async def execute(self, input: GrepInput, state: dict) -> str:
        workspace_path = state["workspace_path"]

        if not self.validate_input(input, workspace_path):
            return "Error : path outside workspace"
        
        search_path = Path(workspace_path) / input.path

        cmd = ["grep", "-rn", "--include", f"*{input.file_pattern}*"]

        if not input.case_sensitive:
            cmd.append("-i")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 1:
            return f"No matches found for '{input.pattern}'"
        
        if result.returncode > 1:
            return f"Error: {result.stderr.strip()}"
        
        lines = result.stdout.splitlines()[:input.max_results]
        output = "\n".join(lines)

        if len(result.stdout.splitlines()) > input.max_results:
            output += f"\n... [truncated — showing {input.max_results} of {len(result.stdout.splitlines())} matches]"

        return trim_tool_output(output, max_tokens=1000)