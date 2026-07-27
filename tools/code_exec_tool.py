import base64

from pydantic import BaseModel

from tools.base import BaseTool, trim_tool_output
from infra.sandbox import run_in_sandbox


class CodeExecInput(BaseModel):
    code: str
    timeout: int = 20


class CodeExecTool(BaseTool):
    name = "code_exec"
    description = (
        "Execute a Python snippet in an isolated, network-disabled Docker sandbox "
        "and return stdout/stderr. Requires human approval."
    )
    risk_level = "high"
    requires_approval = True

    def validate_input(self, input: CodeExecInput, workspace_path: str = "") -> bool:
        return bool(input.code.strip())

    async def execute(self, input: CodeExecInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : code must not be empty"

        workspace_path = state["workspace_path"]
        encoded = base64.b64encode(input.code.encode()).decode()
        command = f"echo {encoded} | base64 -d | python3"

        stdout, stderr, returncode = await run_in_sandbox(
            command,
            workspace_path,
            timeout=input.timeout,
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
