from pathlib import Path
from pydantic import BaseModel
from tools.base import BaseTool, trim_tool_output

class FileWriteInput(BaseModel):
    path: str
    content: str
    mode: str = "overwrite"  # "overwrite" or "append"

class FileWriteTool(BaseTool):
    name = "file_write"
    description = (
        "Write or overwrite a file in the workspace. "
        "Use mode='overwrite' to replace file contents, mode='append' to add to end. "
        "Creates parent directories if needed."
    )
    risk_level = "medium"
    requires_approval = False

    def validate_input(self, input: FileWriteInput, workspace_path: str) -> bool:
        resolved = Path(workspace_path).joinpath(input.path).resolve()
        return str(resolved).startswith(str(Path(workspace_path).resolve()))

    async def execute(self, input: FileWriteInput, state: dict) -> str:
        workspace_path = state["workspace_path"]

        if not self.validate_input(input, workspace_path):
            return "Error: path outside workspace"

        if input.mode not in ("overwrite", "append"):
            return "Error: mode must be 'overwrite' or 'append'"

        full_path = Path(workspace_path) / input.path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if input.mode == "append":
            with full_path.open("a") as f:
                f.write(input.content)
        else:
            full_path.write_text(input.content)

        lines = input.content.count("\n") + 1
        return f"Written {lines} lines to {input.path}"
