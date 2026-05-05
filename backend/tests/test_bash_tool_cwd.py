"""Verify bash_tool sets cwd to thread_data.workspace_path."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deerflow.sandbox.tools import bash_tool


def test_bash_tool_passes_workspace_cwd(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "ok"
    fake_runtime = SimpleNamespace(
        context={"thread_id": "t1", "sandbox_id": "local"},
        state={"thread_data": {"workspace_path": str(workspace)}},
    )
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=fake_sandbox),
        patch("deerflow.sandbox.tools.ensure_thread_directories_exist"),
    ):
        bash_tool.func(runtime=fake_runtime, description="test", command="pwd")
    fake_sandbox.execute_command.assert_called_once_with("pwd", cwd=str(workspace))


def test_bash_tool_no_cwd_when_no_thread_data():
    """Without thread_data, bash_tool calls execute_command with cwd=None (no crash)."""
    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "ok"
    fake_runtime = SimpleNamespace(
        context={"thread_id": "t1"},
        state={},
    )
    with (
        patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=fake_sandbox),
        patch("deerflow.sandbox.tools.ensure_thread_directories_exist"),
    ):
        bash_tool.func(runtime=fake_runtime, description="t", command="true")
    fake_sandbox.execute_command.assert_called_once_with("true", cwd=None)
