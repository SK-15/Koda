import pytest

from tools.memory_search_tool import MemorySearchTool, MemorySearchInput


def _write_domain(workspace_path, domain, content):
    memory_dir = workspace_path / ".koda_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / f"{domain}.md").write_text(content)


class TestMemorySearchTool:
    def setup_method(self):
        self.tool = MemorySearchTool()

    def test_tool_metadata(self):
        assert self.tool.name == "memory_search"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_empty_query(self):
        assert self.tool.validate_input(MemorySearchInput(query="   "), "/ws") is False

    @pytest.mark.asyncio
    async def test_execute_finds_matches(self, tmp_path):
        _write_domain(tmp_path, "prefs", "user likes dark mode\nuser dislikes spam")

        result = await self.tool.execute(
            MemorySearchInput(query="dark mode"),
            {"workspace_path": str(tmp_path), "thread_id": "thread-1"},
        )

        assert "[prefs]" in result
        assert "dark mode" in result

    @pytest.mark.asyncio
    async def test_execute_no_matches(self, tmp_path):
        _write_domain(tmp_path, "prefs", "user likes dark mode")

        result = await self.tool.execute(
            MemorySearchInput(query="zzznomatch"),
            {"workspace_path": str(tmp_path), "thread_id": "thread-1"},
        )

        assert result == "No matches found."

    @pytest.mark.asyncio
    async def test_execute_empty_query(self, tmp_path):
        result = await self.tool.execute(
            MemorySearchInput(query=""),
            {"workspace_path": str(tmp_path), "thread_id": "thread-1"},
        )
        assert result == "Error : query must not be empty"
