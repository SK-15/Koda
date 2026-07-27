import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from tools.base import BaseTool, trim_tool_output


class WebFetchInput(BaseModel):
    url: str
    max_chars: int = 8000


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a URL and return its readable text content (HTML stripped to plain text)."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: WebFetchInput, workspace_path: str = "") -> bool:
        url = input.url.strip()
        return url.startswith("http://") or url.startswith("https://")

    async def execute(self, input: WebFetchInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : url must start with http:// or https://"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                resp = await client.get(input.url)
                resp.raise_for_status()
        except Exception as e:
            return f"Error : fetch failed - {e}"

        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        else:
            text = resp.text

        text = text[: input.max_chars]
        return trim_tool_output(text, max_tokens=2000)
