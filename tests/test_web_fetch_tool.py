import pytest

from tools.web_fetch_tool import WebFetchTool, WebFetchInput


class FakeResponse:
    def __init__(self, text, status_code=200, content_type="text/html"):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    def __init__(self, response=None, raise_exc=None, **kwargs):
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if self._raise_exc:
            raise self._raise_exc
        return self._response


class TestWebFetchTool:
    def setup_method(self):
        self.tool = WebFetchTool()

    def test_tool_metadata(self):
        assert self.tool.name == "web_fetch"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_non_http(self):
        assert self.tool.validate_input(WebFetchInput(url="ftp://example.com"), "/ws") is False

    def test_validate_input_accepts_http(self):
        assert self.tool.validate_input(WebFetchInput(url="https://example.com"), "/ws") is True

    @pytest.mark.asyncio
    async def test_execute_strips_html(self, monkeypatch):
        import tools.web_fetch_tool as wft

        html = "<html><head><script>bad()</script></head><body><nav>Nav</nav><p>Hello world</p></body></html>"
        fake_client = FakeAsyncClient(response=FakeResponse(html))
        monkeypatch.setattr(wft.httpx, "AsyncClient", lambda **kw: fake_client)

        result = await self.tool.execute(
            WebFetchInput(url="https://example.com"), {"workspace_path": "/ws"}
        )

        assert "Hello world" in result
        assert "bad()" not in result
        assert "Nav" not in result

    @pytest.mark.asyncio
    async def test_execute_plain_text(self, monkeypatch):
        import tools.web_fetch_tool as wft

        fake_client = FakeAsyncClient(response=FakeResponse("plain body", content_type="text/plain"))
        monkeypatch.setattr(wft.httpx, "AsyncClient", lambda **kw: fake_client)

        result = await self.tool.execute(
            WebFetchInput(url="https://example.com"), {"workspace_path": "/ws"}
        )

        assert result == "plain body"

    @pytest.mark.asyncio
    async def test_execute_fetch_failure(self, monkeypatch):
        import tools.web_fetch_tool as wft

        fake_client = FakeAsyncClient(raise_exc=RuntimeError("boom"))
        monkeypatch.setattr(wft.httpx, "AsyncClient", lambda **kw: fake_client)

        result = await self.tool.execute(
            WebFetchInput(url="https://example.com"), {"workspace_path": "/ws"}
        )

        assert result == "Error : fetch failed - boom"

    @pytest.mark.asyncio
    async def test_execute_invalid_url(self):
        result = await self.tool.execute(
            WebFetchInput(url="not-a-url"), {"workspace_path": "/ws"}
        )

        assert result == "Error : url must start with http:// or https://"
