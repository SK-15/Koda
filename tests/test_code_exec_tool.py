import pytest

from tools.code_exec_tool import CodeExecTool, CodeExecInput


class TestCodeExecTool:
    def setup_method(self):
        self.tool = CodeExecTool()

    def test_tool_metadata(self):
        assert self.tool.name == "code_exec"
        assert self.tool.risk_level == "high"
        assert self.tool.requires_approval is True

    def test_validate_input_rejects_empty_code(self):
        assert self.tool.validate_input(CodeExecInput(code="   "), "/ws") is False

    def test_validate_input_accepts_code(self):
        assert self.tool.validate_input(CodeExecInput(code="print(1)"), "/ws") is True

    @pytest.mark.asyncio
    async def test_execute_success(self, monkeypatch):
        import tools.code_exec_tool as cet

        async def fake_run_in_sandbox(command, workspace_path, timeout=30):
            assert "base64" in command
            return ("42\n", "", 0)

        monkeypatch.setattr(cet, "run_in_sandbox", fake_run_in_sandbox)

        result = await self.tool.execute(
            CodeExecInput(code="print(42)"), {"workspace_path": "/ws"}
        )

        assert result.strip() == "42"

    @pytest.mark.asyncio
    async def test_execute_nonzero_exit(self, monkeypatch):
        import tools.code_exec_tool as cet

        async def fake_run_in_sandbox(command, workspace_path, timeout=30):
            return ("", "Traceback: boom", 1)

        monkeypatch.setattr(cet, "run_in_sandbox", fake_run_in_sandbox)

        result = await self.tool.execute(
            CodeExecInput(code="raise ValueError()"), {"workspace_path": "/ws"}
        )

        assert "Exit code 1" in result
        assert "Traceback: boom" in result

    @pytest.mark.asyncio
    async def test_execute_empty_code(self):
        result = await self.tool.execute(
            CodeExecInput(code=""), {"workspace_path": "/ws"}
        )
        assert result == "Error : code must not be empty"
