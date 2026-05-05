"""Verify LocalSandbox.execute_command honors a cwd parameter."""
import os

from deerflow.sandbox.local.local_sandbox import LocalSandbox


def test_execute_command_honors_cwd(tmp_path):
    sb = LocalSandbox(id="t")
    out = sb.execute_command("pwd", cwd=str(tmp_path))
    real = os.path.realpath(str(tmp_path))
    assert str(tmp_path) in out or real in out


def test_execute_command_default_cwd_unchanged():
    sb = LocalSandbox(id="t")
    out = sb.execute_command("pwd")
    # No cwd ⇒ inherits backend process cwd
    assert os.getcwd() in out
