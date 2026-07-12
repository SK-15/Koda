import pytest

from tools.web_search_tool import WebSearchTool, WebSearchInput


class FakeTavilyClient:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, max_results=None):
        return {
            "results": [
                {"title": "Result One", "url": "https://example.com/1", "content": "First snippet."},
                {"title": "Result Two", "url": "https://example.com/2", "content": "Second snippet."},
            ]
        }


class EmptyTavilyClient:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, max_results=None):
        return {"results": []}


class ExplodingTavilyClient:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query, max_results=None):
        raise RuntimeError("boom")


class TestWebSearchTool:
    def setup_method(self):
        self.tool = WebSearchTool()

    def test_tool_metadata(self):
        assert self.tool.name == "web_search"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_empty_query(self):
        assert self.tool.validate_input(WebSearchInput(query="   "), "/ws") is False

    def test_validate_input_accepts_query(self):
        assert self.tool.validate_input(WebSearchInput(query="x"), "/ws") is True

    @pytest.mark.asyncio
    async def test_execute_formats_results(self, monkeypatch):
        import tools.web_search_tool as wst
        monkeypatch.setattr(wst, "TavilyClient", FakeTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="langgraph"), {"workspace_path": "/ws"}
        )

        assert "Result One" in result
        assert "https://example.com/1" in result
        assert "First snippet." in result
        assert "Result Two" in result

    @pytest.mark.asyncio
    async def test_execute_no_results(self, monkeypatch):
        import tools.web_search_tool as wst
        monkeypatch.setattr(wst, "TavilyClient", EmptyTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="zzzznomatch"), {"workspace_path": "/ws"}
        )

        assert result == "No results found."

    @pytest.mark.asyncio
    async def test_execute_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        result = await self.tool.execute(
            WebSearchInput(query="langgraph"), {"workspace_path": "/ws"}
        )

        assert result == "Error : TAVILY_API_KEY not configured"

    @pytest.mark.asyncio
    async def test_execute_search_failure(self, monkeypatch):
        import tools.web_search_tool as wst
        monkeypatch.setattr(wst, "TavilyClient", ExplodingTavilyClient)
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="langgraph"), {"workspace_path": "/ws"}
        )

        assert result == "Error : search failed - boom"

    @pytest.mark.asyncio
    async def test_execute_empty_query(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        result = await self.tool.execute(
            WebSearchInput(query="   "), {"workspace_path": "/ws"}
        )

        assert result == "Error : query must not be empty"
