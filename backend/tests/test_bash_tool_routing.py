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

    result = bash_tool.func(runtime=runtime, description="test", command="echo hi")

    fake_sandbox.execute_command.assert_called_once_with("echo hi")
    assert "hello" in result


def test_bash_tool_no_host_bash_gate():
    """bash_tool runs without checking allow_host_bash config."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "ok"
    fake_runtime = SimpleNamespace(
        context={"thread_id": "t1"},
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {"workspace_path": "/tmp/ws"},
        },
    )

    # Force the (now-removed) gate to fire by stubbing the app config so that
    # allow_host_bash would be evaluated as False.  After the gate is removed,
    # bash_tool no longer consults config and returns the sandbox output.
    fake_config = SimpleNamespace(
        sandbox=SimpleNamespace(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            allow_host_bash=False,
            bash_output_max_chars=20000,
        )
    )

    with patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=fake_sandbox), \
         patch("deerflow.sandbox.tools.ensure_thread_directories_exist"), \
         patch("deerflow.sandbox.security.get_app_config", return_value=fake_config), \
         patch("deerflow.config.app_config.get_app_config", return_value=fake_config):
        result = bash_tool.func(runtime=fake_runtime, description="test", command="true")

    assert "ok" in result
    assert "disabled" not in result.lower()
