from abc import ABC, abstractmethod
from pydantic import BaseModel

class ToolInput(BaseModel):
    pass

class BaseTool(ABC):
    name: str
    description: str
    risk_level: str # "low" | "medium" | "high"
    requires_approval: bool

    @abstractmethod
    async def execute(self, input: ToolInput, state: dict) -> str:
        pass

    @abstractmethod
    def validate_input(self, input: ToolInput, workspace_path: str) -> bool:
        pass

def trim_tool_output(output: str, max_tokens: int) -> str:
    words = output.split()
    limit = int(max_tokens * 0.75)
    if len(words) <= limit:
        return output
    return " ".join(words[:limit]) + f"\n... [trimmed - {len(words) - limit} words omitted]"

