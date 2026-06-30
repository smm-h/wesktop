"""Tests for wesktop-specific follow-up features.

Covers:
- 4.2: MCP tool modules (wesktop.mcp_tools/)
- 2.4: wesktop.run() accepts reload parameter
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 4.2 MCP tool modules -- basic import and function signatures
# ---------------------------------------------------------------------------


class TestMCPToolModules:
    def test_filesystem_module_importable(self):
        """Filesystem tool module is importable with expected functions."""
        from wesktop.mcp_tools import filesystem

        assert callable(filesystem.read_file)
        assert callable(filesystem.write_file)
        assert callable(filesystem.edit_file)
        assert callable(filesystem.list_files)
        assert callable(filesystem.search_files)

    def test_git_module_importable(self):
        """Git tool module is importable with expected functions."""
        from wesktop.mcp_tools import git

        assert callable(git.git_status)
        assert callable(git.git_diff)
        assert callable(git.git_commit)
        assert callable(git.git_log)

    def test_testing_module_importable(self):
        """Testing tool module is importable with expected functions."""
        from wesktop.mcp_tools import testing

        assert callable(testing.run_tests)

    def test_deployment_module_importable(self):
        """Deployment tool module is importable with expected functions."""
        from wesktop.mcp_tools import deployment

        assert callable(deployment.stage_branch)
        assert callable(deployment.create_prod_pr)
        assert callable(deployment.check_pipeline)

    def test_review_module_importable(self):
        """Review tool module is importable with expected functions."""
        from wesktop.mcp_tools import review

        assert callable(review.post_review_comment)

    def test_ask_user_module_importable(self):
        """Ask-user tool module is importable with expected functions."""
        from wesktop.mcp_tools import ask_user

        assert callable(ask_user.ask_user)

    def test_filesystem_read_file_nonexistent(self, tmp_path):
        """read_file returns error for nonexistent file."""
        from wesktop.mcp_tools.filesystem import read_file

        result = read_file(str(tmp_path), "nonexistent.txt")
        assert result.startswith("Error:")

    def test_filesystem_write_and_read(self, tmp_path):
        """write_file + read_file round-trip works."""
        from wesktop.mcp_tools.filesystem import read_file, write_file

        result = write_file(str(tmp_path), "test.txt", "hello world")
        assert "Wrote" in result

        content = read_file(str(tmp_path), "test.txt")
        assert content == "hello world"

    def test_filesystem_path_traversal_blocked(self, tmp_path):
        """Path traversal attempts are blocked."""
        from wesktop.mcp_tools.filesystem import read_file

        with pytest.raises(ValueError, match="Path traversal"):
            read_file(str(tmp_path), "../../../etc/passwd")

    def test_filesystem_list_files(self, tmp_path):
        """list_files returns directory listing."""
        from wesktop.mcp_tools.filesystem import list_files, write_file

        write_file(str(tmp_path), "a.txt", "a")
        (tmp_path / "subdir").mkdir()

        result = list_files(str(tmp_path))
        assert "subdir/" in result
        assert "a.txt" in result

    def test_filesystem_edit_file(self, tmp_path):
        """edit_file performs find-and-replace."""
        from wesktop.mcp_tools.filesystem import edit_file, read_file, write_file

        write_file(str(tmp_path), "test.txt", "hello world")
        result = edit_file(str(tmp_path), "test.txt", "hello", "goodbye")
        assert "Replaced" in result

        content = read_file(str(tmp_path), "test.txt")
        assert content == "goodbye world"

    def test_git_status_in_repo(self, tmp_path):
        """git_status works in an initialized repo."""
        import subprocess

        from wesktop.mcp_tools.git import git_status

        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        result = git_status(str(tmp_path))
        assert "Error" not in result


# ---------------------------------------------------------------------------
# 2.4 Forward reload to run()
# ---------------------------------------------------------------------------


class TestRunReload:
    def test_run_accepts_reload_parameter(self):
        """wesktop.run() accepts reload=True without TypeError."""
        import inspect

        from wesktop import run

        sig = inspect.signature(run)
        assert "reload" in sig.parameters
        # Verify it has a default of False
        assert sig.parameters["reload"].default is False
