import pytest

from tools.http_request_tool import HttpRequestTool, HttpRequestInput


class FakeResponse:
    def __init__(self, text="ok", status_code=200):
        self.text = text
        self.status_code = status_code


class FakeAsyncClient:
    def __init__(self, response=None, raise_exc=None, **kwargs):
        self._response = response
        self._raise_exc = raise_exc
        self.last_call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, headers=None, json=None):
        self.last_call = {"method": method, "url": url, "headers": headers, "json": json}
        if self._raise_exc:
            raise self._raise_exc
        return self._response


class TestHttpRequestTool:
    def setup_method(self):
        self.tool = HttpRequestTool()

    def test_tool_metadata(self):
        assert self.tool.name == "http_request"
        assert self.tool.risk_level == "medium"
        assert self.tool.requires_approval is True

    def test_validate_input_rejects_bad_method(self):
        input = HttpRequestInput(url="https://example.com", method="TRACE")
        assert self.tool.validate_input(input, "/ws") is False

    def test_validate_input_rejects_non_http_url(self):
        input = HttpRequestInput(url="file:///etc/passwd")
        assert self.tool.validate_input(input, "/ws") is False

    def test_validate_input_accepts_get(self):
        input = HttpRequestInput(url="https://example.com")
        assert self.tool.validate_input(input, "/ws") is True

    @pytest.mark.asyncio
    async def test_execute_returns_status_and_body(self, monkeypatch):
        import tools.http_request_tool as hrt

        fake_client = FakeAsyncClient(response=FakeResponse(text='{"ok":true}', status_code=200))
        monkeypatch.setattr(hrt.httpx, "AsyncClient", lambda **kw: fake_client)

        result = await self.tool.execute(
            HttpRequestInput(url="https://example.com/api", method="POST", json_body={"a": 1}),
            {"workspace_path": "/ws"},
        )

        assert "Status: 200" in result
        assert '{"ok":true}' in result
        assert fake_client.last_call["method"] == "POST"
        assert fake_client.last_call["json"] == {"a": 1}

    @pytest.mark.asyncio
    async def test_execute_request_failure(self, monkeypatch):
        import tools.http_request_tool as hrt

        fake_client = FakeAsyncClient(raise_exc=RuntimeError("timeout"))
        monkeypatch.setattr(hrt.httpx, "AsyncClient", lambda **kw: fake_client)

        result = await self.tool.execute(
            HttpRequestInput(url="https://example.com"), {"workspace_path": "/ws"}
        )

        assert result == "Error : request failed - timeout"

    @pytest.mark.asyncio
    async def test_execute_invalid_input(self):
        result = await self.tool.execute(
            HttpRequestInput(url="https://example.com", method="TRACE"),
            {"workspace_path": "/ws"},
        )

        assert result == "Error : invalid url or unsupported method"
