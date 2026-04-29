"""Integration tests for the bash_tool → bwrap wiring.

These verify that ``bash_tool`` (in local-sandbox mode) routes to
``execute_bwrap`` with the expected arguments instead of running the command
directly on the host. The actual bwrap execution is patched so these tests do
not require ``bubblewrap`` to be installed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deerflow.sandbox.tools import bash_tool

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}


def _make_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": dict(_THREAD_DATA)},
        context={"thread_id": "t1"},
    )


def test_bash_tool_routes_to_bwrap_with_user_data_dir(monkeypatch):
    captured: dict = {}

    def fake_execute_bwrap(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return 0, "ok\n", ""

    monkeypatch.setattr("deerflow.sandbox.tools.execute_bwrap", fake_execute_bwrap)
    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_sandbox_initialized",
        lambda runtime: SimpleNamespace(execute_command=lambda c: pytest.fail("must not run host bash")),
    )
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_host_path", lambda: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_custom_mounts", lambda: [])

    result = bash_tool.func(
        runtime=_make_runtime(),
        description="run cmd",
        command="echo hi",
    )

    assert "ok" in result
    # The user-data host dir is the *parent* of workspace_path:
    assert captured["user_data_host_dir"] == "/tmp/deer-flow/threads/t1/user-data"
    # Command is forwarded unchanged — bwrap will run it inside the sandbox
    # where /mnt/user-data is a real bind mount.
    assert captured["command"] == "echo hi"


def test_bash_tool_passes_skills_dir_to_bwrap_when_configured(monkeypatch):
    captured: dict = {}

    def fake_execute_bwrap(command, **kwargs):
        captured.update(kwargs)
        return 0, "", ""

    monkeypatch.setattr("deerflow.sandbox.tools.execute_bwrap", fake_execute_bwrap)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda r: SimpleNamespace())
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda r: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_host_path", lambda: "/host/skills")
    monkeypatch.setattr("deerflow.sandbox.tools._get_custom_mounts", lambda: [])

    bash_tool.func(runtime=_make_runtime(), description="x", command="echo")

    assert captured["skills_host_dir"] == "/host/skills"


def test_bash_tool_passes_custom_mounts_to_bwrap(monkeypatch):
    captured: dict = {}

    def fake_execute_bwrap(command, **kwargs):
        captured.update(kwargs)
        return 0, "", ""

    monkeypatch.setattr("deerflow.sandbox.tools.execute_bwrap", fake_execute_bwrap)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda r: SimpleNamespace())
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda r: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_host_path", lambda: None)
    monkeypatch.setattr(
        "deerflow.sandbox.tools._get_custom_mounts",
        lambda: [
            SimpleNamespace(host_path="/srv/data", container_path="/mnt/data", read_only=False),
            SimpleNamespace(host_path="/srv/ref", container_path="/mnt/ref", read_only=True),
        ],
    )

    bash_tool.func(runtime=_make_runtime(), description="x", command="echo")

    extra = captured["extra_mounts"]
    assert len(extra) == 2
    assert (extra[0].host_path, extra[0].container_path, extra[0].read_only) == ("/srv/data", "/mnt/data", False)
    assert (extra[1].host_path, extra[1].container_path, extra[1].read_only) == ("/srv/ref", "/mnt/ref", True)


def test_bash_tool_returns_exit_code_when_nonzero(monkeypatch):
    monkeypatch.setattr(
        "deerflow.sandbox.tools.execute_bwrap",
        lambda command, **kw: (7, "out\n", "err\n"),
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda r: SimpleNamespace())
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda r: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_host_path", lambda: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_custom_mounts", lambda: [])

    result = bash_tool.func(runtime=_make_runtime(), description="x", command="false")

    assert "out" in result
    assert "err" in result
    assert "Exit Code: 7" in result


def test_bash_tool_propagates_bwrap_not_installed(monkeypatch):
    """When bwrap is missing, bash_tool surfaces a clear error (failed-fast)."""
    from deerflow.sandbox.local.bwrap_runner import BwrapNotInstalledError

    def fake_execute_bwrap(command, **kw):
        raise BwrapNotInstalledError("bwrap (bubblewrap) is not installed.")

    monkeypatch.setattr("deerflow.sandbox.tools.execute_bwrap", fake_execute_bwrap)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda r: SimpleNamespace())
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: True)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda r: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_skills_host_path", lambda: None)
    monkeypatch.setattr("deerflow.sandbox.tools._get_custom_mounts", lambda: [])

    result = bash_tool.func(runtime=_make_runtime(), description="x", command="echo")

    assert "bwrap" in result.lower()
    assert "not installed" in result.lower()
