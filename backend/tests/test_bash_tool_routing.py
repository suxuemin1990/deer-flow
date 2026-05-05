"""Routing test: bash_tool always delegates to sandbox.execute_command."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from deerflow.sandbox.tools import bash_tool


def test_bash_tool_uses_sandbox_execute_command(monkeypatch):
    """bash_tool always delegates to sandbox.execute_command (no bwrap branch).

    Even when the runtime points at a local sandbox, the tool must route through
    Sandbox.execute_command rather than a bwrap-specific code path.
    """
    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "hello"
    runtime = SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
                "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
                "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
            },
        },
        context={"thread_id": "t1"},
    )

    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_sandbox_initialized", lambda r: fake_sandbox
    )
    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_thread_directories_exist", lambda r: None
    )
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)

    result = bash_tool.func(runtime=runtime, description="test", command="echo hi")

    fake_sandbox.execute_command.assert_called_once_with("echo hi")
    assert "hello" in result
