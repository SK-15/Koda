import asyncio
import os

from pydantic import BaseModel
from tavily import TavilyClient

from tools.base import BaseTool, trim_tool_output


class WebSearchInput(BaseModel):
    query: str
    max_results: int = 5


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information. Returns titles, URLs, and snippets."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: WebSearchInput, workspace_path: str) -> bool:
        return bool(input.query.strip())

    async def execute(self, input: WebSearchInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : query must not be empty"

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return "Error : TAVILY_API_KEY not configured"

        try:
            response = await asyncio.to_thread(
                TavilyClient(api_key=api_key).search,
                input.query,
                max_results=input.max_results,
            )
        except Exception as e:
            return f"Error : search failed - {e}"

        results = response.get("results", [])
        if not results:
            return "No results found."

        formatted = "\n\n".join(
            f"{r['title']}\n{r['url']}\n{r['content']}" for r in results
        )
        return trim_tool_output(formatted, max_tokens=2000)
