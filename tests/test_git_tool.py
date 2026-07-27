import subprocess

import pytest

from tools.git_tool import GitTool, GitInput


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=repo, capture_output=True)
    (repo / "file.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return str(repo)


class TestGitTool:
    def setup_method(self):
        self.tool = GitTool()

    def test_tool_metadata(self):
        assert self.tool.name == "git"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_disallowed_subcommand(self):
        assert self.tool.validate_input(GitInput(subcommand="push"), "/ws") is False

    def test_validate_input_accepts_status(self):
        assert self.tool.validate_input(GitInput(subcommand="status"), "/ws") is True

    @pytest.mark.asyncio
    async def test_execute_status(self, git_repo):
        result = await self.tool.execute(
            GitInput(subcommand="status"), {"workspace_path": git_repo}
        )
        assert "clean" in result.lower() or "nothing to commit" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_log(self, git_repo):
        result = await self.tool.execute(
            GitInput(subcommand="log", args=["--oneline"]), {"workspace_path": git_repo}
        )
        assert "init" in result

    @pytest.mark.asyncio
    async def test_execute_blocked_subcommand(self, git_repo):
        result = await self.tool.execute(
            GitInput(subcommand="push"), {"workspace_path": git_repo}
        )
        assert result == "Error : subcommand not allowed - 'push'"

    @pytest.mark.asyncio
    async def test_execute_invalid_repo_path(self, tmp_path):
        empty_dir = tmp_path / "not_a_repo"
        empty_dir.mkdir()
        result = await self.tool.execute(
            GitInput(subcommand="log"), {"workspace_path": str(empty_dir)}
        )
        assert "Exit code" in result
