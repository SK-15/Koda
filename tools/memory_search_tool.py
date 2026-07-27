from pydantic import BaseModel

from tools.base import BaseTool, trim_tool_output
from memory.memory_manager import MemoryManager


class MemorySearchInput(BaseModel):
    query: str
    max_matches: int = 20


class MemorySearchTool(BaseTool):
    name = "memory_search"
    description = "Search koda's own workspace memory (.koda_memory/*.md) for lines matching a keyword."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: MemorySearchInput, workspace_path: str = "") -> bool:
        return bool(input.query.strip())

    async def execute(self, input: MemorySearchInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : query must not be empty"

        workspace_path = state["workspace_path"]
        thread_id = state.get("thread_id", "default")
        manager = MemoryManager(thread_id, workspace_path)
        domains = manager.load_all_domains()

        needle = input.query.lower()
        matches = []
        for domain, content in domains.items():
            for line in content.splitlines():
                if needle in line.lower():
                    matches.append(f"[{domain}] {line.strip()}")
                    if len(matches) >= input.max_matches:
                        break
            if len(matches) >= input.max_matches:
                break

        if not matches:
            return "No matches found."

        return trim_tool_output("\n".join(matches), max_tokens=2000)
