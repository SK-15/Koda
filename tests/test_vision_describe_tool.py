import pytest

from tools.vision_describe_tool import VisionDescribeTool, VisionDescribeInput


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content="a cat sitting on a mat", raise_exc=None):
        self._content = content
        self._raise_exc = raise_exc
        self.last_messages = None

    async def ainvoke(self, messages):
        self.last_messages = messages
        if self._raise_exc:
            raise self._raise_exc
        return FakeResponse(self._content)


class TestVisionDescribeTool:
    def setup_method(self):
        self.tool = VisionDescribeTool()

    def test_tool_metadata(self):
        assert self.tool.name == "vision_describe"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_empty_image(self):
        assert self.tool.validate_input(VisionDescribeInput(image="  "), "/ws") is False

    @pytest.mark.asyncio
    async def test_execute_with_url(self, monkeypatch):
        import llm.router as router

        fake_llm = FakeLLM()
        monkeypatch.setattr(router, "_build_base_llm", lambda model: fake_llm)

        result = await self.tool.execute(
            VisionDescribeInput(image="https://example.com/cat.png"),
            {"workspace_path": "/ws"},
        )

        assert result == "a cat sitting on a mat"
        image_block = fake_llm.last_messages[0].content[1]
        assert image_block["image_url"]["url"] == "https://example.com/cat.png"

    @pytest.mark.asyncio
    async def test_execute_with_local_file(self, monkeypatch, tmp_path):
        import llm.router as router

        img_path = tmp_path / "pic.png"
        img_path.write_bytes(b"\x89PNG\r\n fake bytes")

        fake_llm = FakeLLM(content="a local image")
        monkeypatch.setattr(router, "_build_base_llm", lambda model: fake_llm)

        result = await self.tool.execute(
            VisionDescribeInput(image="pic.png"),
            {"workspace_path": str(tmp_path)},
        )

        assert result == "a local image"
        image_block = fake_llm.last_messages[0].content[1]
        assert image_block["image_url"]["url"].startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_execute_missing_local_file(self, tmp_path):
        result = await self.tool.execute(
            VisionDescribeInput(image="missing.png"),
            {"workspace_path": str(tmp_path)},
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_execute_path_outside_workspace(self, tmp_path):
        result = await self.tool.execute(
            VisionDescribeInput(image="../../etc/passwd"),
            {"workspace_path": str(tmp_path)},
        )
        assert "not found or outside workspace" in result

    @pytest.mark.asyncio
    async def test_execute_llm_failure(self, monkeypatch):
        import llm.router as router

        fake_llm = FakeLLM(raise_exc=RuntimeError("model unavailable"))
        monkeypatch.setattr(router, "_build_base_llm", lambda model: fake_llm)

        result = await self.tool.execute(
            VisionDescribeInput(image="https://example.com/cat.png"),
            {"workspace_path": "/ws"},
        )

        assert result == "Error : vision request failed - model unavailable"
