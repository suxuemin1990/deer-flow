"""Run LLM-issued bash commands inside bubblewrap (``bwrap``).

bwrap gives the LLM a real ``/mnt/user-data`` mount — created via a bind mount
from the per-thread host workspace — instead of relying on string-level path
rewriting in the command. This means scripts that hard-code paths like
``open("/mnt/user-data/uploads/foo")`` actually find their files at runtime.

Network is intentionally NOT isolated here so that ``pip install`` and other
LLM-driven network operations continue to work. PID, IPC and UTS namespaces
are isolated; system directories are bind-mounted read-only.

The bwrap binary must be installed on the host (``apt install bubblewrap``);
``execute_bwrap`` raises :class:`BwrapNotInstalledError` if not found, instead
of silently falling back to host execution.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

# Container-side path conventions that match the rest of the harness
# (``deerflow.sandbox.tools`` uses these prefixes when constructing prompts).
_USER_DATA_CONTAINER = "/mnt/user-data"
_USER_DATA_WORKSPACE = "/mnt/user-data/workspace"
_SKILLS_CONTAINER = "/mnt/skills"

# Read-only host directories the LLM bash session needs to find binaries,
# shared libraries, and system configuration. ``--ro-bind-try`` is used so
# that hosts missing one of these (e.g. minimal containers without /sbin)
# do not fail; bwrap silently skips entries whose source does not exist.
_SYSTEM_RO_BIND_DIRS: tuple[str, ...] = (
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/etc",
    "/sbin",
    "/opt",
    "/var",
)


class BwrapNotInstalledError(RuntimeError):
    """Raised when the ``bwrap`` binary is not installed on the host."""


@dataclass(frozen=True)
class BwrapMount:
    """Additional bind mount injected into the bwrap sandbox.

    Use this for skills directories beyond ``/mnt/skills`` and for any custom
    mount declared via ``config.yaml > sandbox.mounts``.
    """

    host_path: str
    container_path: str
    read_only: bool = False


def build_bwrap_argv(
    command: str,
    *,
    user_data_host_dir: str,
    skills_host_dir: str | None = None,
    extra_mounts: list[BwrapMount] | None = None,
    bwrap_path: str = "bwrap",
    shell: str = "/bin/bash",
) -> list[str]:
    """Construct the argv for invoking ``bwrap`` to run *command*.

    Args:
        command: Raw bash command. May contain ``/mnt/user-data`` paths;
            those are real inside the sandbox thanks to the bind mount.
        user_data_host_dir: Host directory bind-mounted at
            ``/mnt/user-data``. Must contain a ``workspace`` subdir before
            invocation; ``--chdir`` lands the shell there.
        skills_host_dir: Optional host directory bind-mounted read-only at
            ``/mnt/skills``. Omit when no skills are configured.
        extra_mounts: Additional bind mounts (skills sub-mounts, custom
            sandbox mounts from config).
        bwrap_path: Path to the bwrap binary; override only for tests or
            non-standard installs.
        shell: Path to the shell binary used to execute *command*.

    Returns:
        argv list ready for :func:`subprocess.run`. The structure is::

            [bwrap_path, ...flags..., --, shell, -lc, command]
    """
    argv: list[str] = [bwrap_path]

    # Read-only system directories. ``ro-bind-try`` skips missing dirs
    # rather than failing, which keeps minimal hosts working.
    for sysdir in _SYSTEM_RO_BIND_DIRS:
        argv += ["--ro-bind-try", sysdir, sysdir]

    # /proc, /dev, /tmp need explicit handling: --proc/--dev create a fresh
    # virtual mount in the new namespace; tmpfs gives an isolated /tmp.
    argv += ["--proc", "/proc"]
    argv += ["--dev", "/dev"]
    argv += ["--tmpfs", "/tmp"]
    argv += ["--tmpfs", "/run"]

    # Per-thread workspace bind: this is what makes /mnt/user-data really
    # exist inside the sandbox.
    argv += ["--bind", user_data_host_dir, _USER_DATA_CONTAINER]

    # Skills are read-only by convention; the caller passes None when no
    # skills directory is configured.
    if skills_host_dir:
        argv += ["--ro-bind", skills_host_dir, _SKILLS_CONTAINER]

    # User-supplied additional mounts.
    for mount in extra_mounts or []:
        flag = "--ro-bind" if mount.read_only else "--bind"
        argv += [flag, mount.host_path, mount.container_path]

    # Namespace isolation. Network is intentionally shared so that
    # ``pip install`` / network calls keep working.
    argv += [
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
    ]

    # Land in the workspace by default. Relative paths in user commands
    # are then anchored to /mnt/user-data/workspace, matching the previous
    # ``_apply_cwd_prefix`` behaviour.
    argv += ["--chdir", _USER_DATA_WORKSPACE]

    # Trailing -- shell -lc <command> form. ``-lc`` makes bash a login shell
    # so /etc/profile.d activations (e.g. virtualenv setups) still apply.
    argv += ["--", shell, "-lc", command]

    return argv


def execute_bwrap(
    command: str,
    *,
    user_data_host_dir: str,
    skills_host_dir: str | None = None,
    extra_mounts: list[BwrapMount] | None = None,
    timeout: int = 600,
    shell: str = "/bin/bash",
) -> tuple[int, str, str]:
    """Run *command* inside bwrap and return ``(returncode, stdout, stderr)``.

    Raises:
        BwrapNotInstalledError: If the ``bwrap`` binary cannot be located on
            ``PATH``. Failed-fast so deployments do not silently degrade to
            host execution.
        subprocess.TimeoutExpired: When *timeout* is exceeded.
    """
    bwrap_path = shutil.which("bwrap")
    if bwrap_path is None:
        raise BwrapNotInstalledError(
            "bwrap (bubblewrap) is not installed. Install it (e.g. "
            "'apt install bubblewrap') or switch to a different sandbox "
            "provider via config.yaml > sandbox.use."
        )

    argv = build_bwrap_argv(
        command,
        user_data_host_dir=user_data_host_dir,
        skills_host_dir=skills_host_dir,
        extra_mounts=extra_mounts,
        bwrap_path=bwrap_path,
        shell=shell,
    )

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.returncode, completed.stdout, completed.stderr
