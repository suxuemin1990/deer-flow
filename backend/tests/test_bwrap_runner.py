"""Tests for the bubblewrap (bwrap) bash command runner.

The runner replaces direct host bash execution in ``LocalSandbox`` with a
bind-mounted bwrap invocation so that LLM-issued bash commands see a real
``/mnt/user-data`` mount point (fixing the long-standing footgun where
absolute paths inside generated scripts hit non-existent host paths).

Network is intentionally NOT isolated (``--unshare-net`` is omitted) so that
``pip install`` and other LLM-driven network operations continue to work.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# build_bwrap_argv
# ---------------------------------------------------------------------------


def test_build_bwrap_argv_starts_with_bwrap_executable():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/var/foo")
    assert argv[0] == "bwrap"


def test_build_bwrap_argv_binds_user_data_dir_readwrite():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/threads/abc/user-data")

    # Adjacent --bind <host> /mnt/user-data triplet must be present.
    triplet = ("--bind", "/host/threads/abc/user-data", "/mnt/user-data")
    pairs = list(zip(argv, argv[1:], argv[2:]))
    assert triplet in pairs


def test_build_bwrap_argv_binds_skills_dir_readonly_when_provided():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv(
        "echo hi",
        user_data_host_dir="/host/u",
        skills_host_dir="/host/skills",
    )

    triplet = ("--ro-bind", "/host/skills", "/mnt/skills")
    pairs = list(zip(argv, argv[1:], argv[2:]))
    assert triplet in pairs


def test_build_bwrap_argv_skips_skills_when_not_provided():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")
    assert "/mnt/skills" not in argv


def test_build_bwrap_argv_default_isolation_flags():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")

    for flag in ("--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent"):
        assert flag in argv, f"expected isolation flag {flag} missing from argv"


def test_build_bwrap_argv_does_not_isolate_network_by_default():
    """Network must be shared so 'pip install' still works."""
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")
    assert "--unshare-net" not in argv


def test_build_bwrap_argv_chdir_workspace():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")
    assert ("--chdir", "/mnt/user-data/workspace") in list(zip(argv, argv[1:]))


def test_build_bwrap_argv_mounts_proc_dev_and_tmpfs():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")
    pairs = list(zip(argv, argv[1:]))
    assert ("--proc", "/proc") in pairs
    assert ("--dev", "/dev") in pairs
    assert ("--tmpfs", "/tmp") in pairs


def test_build_bwrap_argv_includes_system_readonly_binds():
    """LLM bash needs system binaries; expose them read-only."""
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")
    triples = list(zip(argv, argv[1:], argv[2:]))

    for system_dir in ("/usr", "/lib", "/lib64", "/bin", "/etc", "/sbin"):
        assert (
            "--ro-bind-try",
            system_dir,
            system_dir,
        ) in triples, f"missing read-only system bind for {system_dir}"


def test_build_bwrap_argv_command_appended_after_double_dash():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv(
        "echo $HOME && ls",
        user_data_host_dir="/host/u",
        shell="/bin/bash",
    )

    # Final tail must be: -- <shell> -lc <command>
    assert argv[-4:] == ["--", "/bin/bash", "-lc", "echo $HOME && ls"]


def test_build_bwrap_argv_double_dash_appears_exactly_once():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv("echo hi", user_data_host_dir="/host/u")
    assert argv.count("--") == 1


def test_build_bwrap_argv_extra_mounts_rw():
    from deerflow.sandbox.local.bwrap_runner import BwrapMount, build_bwrap_argv

    argv = build_bwrap_argv(
        "echo hi",
        user_data_host_dir="/host/u",
        extra_mounts=[BwrapMount(host_path="/srv/data", container_path="/mnt/data", read_only=False)],
    )
    triples = list(zip(argv, argv[1:], argv[2:]))
    assert ("--bind", "/srv/data", "/mnt/data") in triples


def test_build_bwrap_argv_extra_mounts_ro():
    from deerflow.sandbox.local.bwrap_runner import BwrapMount, build_bwrap_argv

    argv = build_bwrap_argv(
        "echo hi",
        user_data_host_dir="/host/u",
        extra_mounts=[BwrapMount(host_path="/srv/ref", container_path="/mnt/ref", read_only=True)],
    )
    triples = list(zip(argv, argv[1:], argv[2:]))
    assert ("--ro-bind", "/srv/ref", "/mnt/ref") in triples


def test_build_bwrap_argv_supports_custom_bwrap_path():
    from deerflow.sandbox.local.bwrap_runner import build_bwrap_argv

    argv = build_bwrap_argv(
        "echo hi",
        user_data_host_dir="/host/u",
        bwrap_path="/opt/custom/bwrap",
    )
    assert argv[0] == "/opt/custom/bwrap"


# ---------------------------------------------------------------------------
# execute_bwrap (integration with subprocess + bwrap binary)
# ---------------------------------------------------------------------------


def test_execute_bwrap_raises_when_bwrap_missing(monkeypatch):
    from deerflow.sandbox.local import bwrap_runner
    from deerflow.sandbox.local.bwrap_runner import BwrapNotInstalledError, execute_bwrap

    monkeypatch.setattr(bwrap_runner.shutil, "which", lambda _name: None)

    with pytest.raises(BwrapNotInstalledError):
        execute_bwrap("echo hi", user_data_host_dir="/tmp")


# Real-bwrap integration tests — skipped on hosts without bubblewrap installed.

import shutil as _shutil  # noqa: E402

_HAS_BWRAP = _shutil.which("bwrap") is not None
requires_bwrap = pytest.mark.skipif(not _HAS_BWRAP, reason="bwrap not installed")


@requires_bwrap
def test_execute_bwrap_real_workspace_visible(tmp_path):
    """User-data bind mount makes /mnt/user-data really exist inside bwrap."""
    from deerflow.sandbox.local.bwrap_runner import execute_bwrap

    user_data = tmp_path / "user-data"
    workspace = user_data / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "hello.txt").write_text("from-host")

    rc, out, err = execute_bwrap(
        "cat /mnt/user-data/workspace/hello.txt",
        user_data_host_dir=str(user_data),
    )

    assert rc == 0, f"stderr={err}"
    assert out.strip() == "from-host"


@requires_bwrap
def test_execute_bwrap_real_writes_persist_to_host(tmp_path):
    """Writes to /mnt/user-data inside bwrap appear on the host."""
    from deerflow.sandbox.local.bwrap_runner import execute_bwrap

    user_data = tmp_path / "user-data"
    (user_data / "workspace").mkdir(parents=True)

    rc, _, err = execute_bwrap(
        "echo from-bwrap > /mnt/user-data/workspace/out.txt",
        user_data_host_dir=str(user_data),
    )
    assert rc == 0, f"stderr={err}"

    assert (user_data / "workspace" / "out.txt").read_text().strip() == "from-bwrap"


@requires_bwrap
def test_execute_bwrap_real_pid_isolated(tmp_path):
    """PID namespace isolation: 'ps' inside bwrap should NOT see the host's many processes."""
    from deerflow.sandbox.local.bwrap_runner import execute_bwrap

    user_data = tmp_path / "user-data"
    (user_data / "workspace").mkdir(parents=True)

    rc, out, err = execute_bwrap(
        "ls /proc | grep -c '^[0-9]'",
        user_data_host_dir=str(user_data),
    )
    assert rc == 0, f"stderr={err}"
    pid_count = int(out.strip())
    # In an isolated PID ns we should see only a tiny number of PIDs (the
    # shell + maybe the grep). On the host, the count is hundreds-to-thousands.
    assert pid_count < 20, f"expected isolated pid namespace, got {pid_count} pids"


@requires_bwrap
def test_execute_bwrap_real_workdir_is_workspace(tmp_path):
    from deerflow.sandbox.local.bwrap_runner import execute_bwrap

    user_data = tmp_path / "user-data"
    (user_data / "workspace").mkdir(parents=True)

    rc, out, _ = execute_bwrap("pwd", user_data_host_dir=str(user_data))
    assert rc == 0
    assert out.strip() == "/mnt/user-data/workspace"


@requires_bwrap
def test_execute_bwrap_real_nonzero_exit_returned(tmp_path):
    from deerflow.sandbox.local.bwrap_runner import execute_bwrap

    user_data = tmp_path / "user-data"
    (user_data / "workspace").mkdir(parents=True)

    rc, _, _ = execute_bwrap("exit 7", user_data_host_dir=str(user_data))
    assert rc == 7
