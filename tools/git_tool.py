import asyncio
import subprocess

from pydantic import BaseModel

from tools.base import BaseTool, trim_tool_output

ALLOWED_SUBCOMMANDS = {"status", "diff", "log", "show", "blame", "branch"}


class GitInput(BaseModel):
    subcommand: str
    args: list[str] = []


class GitTool(BaseTool):
    name = "git"
    description = (
        "Run a read-only git inspection command (status/diff/log/show/blame/branch) "
        "against the workspace repo."
    )
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: GitInput, workspace_path: str = "") -> bool:
        return input.subcommand in ALLOWED_SUBCOMMANDS

    async def execute(self, input: GitInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return f"Error : subcommand not allowed - '{input.subcommand}'"

        workspace_path = state["workspace_path"]
        cmd = ["git", input.subcommand, *input.args]

        def run():
            return subprocess.run(
                cmd,
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=20,
            )

        try:
            proc = await asyncio.to_thread(run)
        except subprocess.TimeoutExpired:
            return "Error : git command timed out"
        except Exception as e:
            return f"Error : git command failed - {e}"

        if proc.returncode != 0:
            return f"Exit code {proc.returncode}\n{proc.stderr}"

        return trim_tool_output(proc.stdout, max_tokens=2000)
