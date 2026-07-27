import httpx
from pydantic import BaseModel

from tools.base import BaseTool, trim_tool_output

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class HttpRequestInput(BaseModel):
    url: str
    method: str = "GET"
    headers: dict[str, str] = {}
    json_body: dict | list | None = None


class HttpRequestTool(BaseTool):
    name = "http_request"
    description = (
        "Make an HTTP request (GET/POST/PUT/PATCH/DELETE) to an external API or URL. "
        "Requires human approval since it can trigger side effects on external systems."
    )
    risk_level = "medium"
    requires_approval = True

    def validate_input(self, input: HttpRequestInput, workspace_path: str = "") -> bool:
        url = input.url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return False
        return input.method.upper() in ALLOWED_METHODS

    async def execute(self, input: HttpRequestInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : invalid url or unsupported method"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                resp = await client.request(
                    input.method.upper(),
                    input.url,
                    headers=input.headers,
                    json=input.json_body,
                )
        except Exception as e:
            return f"Error : request failed - {e}"

        body = resp.text
        output = f"Status: {resp.status_code}\n{body}"
        return trim_tool_output(output, max_tokens=2000)
