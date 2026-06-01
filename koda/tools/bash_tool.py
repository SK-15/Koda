from pydantic import BaseModel
from tools.base import BaseTool, trim_tool_output
from tools.bash_validator import validate_bash_command
from infra.sandbox import run_in_sandbox

class BashInput(BaseModel):
      command: str


class BashTool(BaseTool):
    name = "bash"
    description = "Execute a shell command in a sandboxed environment. Requires human approval."
    risk_level = "high"
    requires_approval = True

    def validate_input(self, input: BashInput, workspace_path: str = "") -> bool:
        allowed, _ = validate_bash_command(input.command)
        return allowed

    async def execute(self, input: BashInput, state: dict) -> str:
        allowed, reason = validate_bash_command(input.command)
        if not allowed:
            return f"Blocked: {reason}"

        workspace_path = state["workspace_path"]
        stdout, stderr, returncode = await run_in_sandbox(
            input.command,
            workspace_path,
        )

        if returncode != 0:
            output = f"Exit code {returncode}\n"
            if stderr:
                output += f"stderr:\n{stderr}\n"
            if stdout:
                output += f"stdout:\n{stdout}"
        else:
            output = stdout
            if stderr:
                output += f"\nstderr:\n{stderr}"

        return trim_tool_output(output, max_tokens=2000)