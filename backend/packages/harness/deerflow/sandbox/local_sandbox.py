"""Single concrete Sandbox: host-direct, no isolation.

Stage 6 of remove-sandbox-isolation collapsed the previous ``LocalSandbox``
plus ``LocalSandboxProvider`` plus virtual ``path_mappings`` machinery into
this one class. There is no longer any container-vs-host path translation:
every method operates directly on host filesystem paths.
"""

from __future__ import annotations

import ntpath
import os
import shutil
import subprocess
from pathlib import Path

from deerflow.sandbox.list_dir import list_dir
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.search import GrepMatch, find_glob_matches, find_grep_matches


class LocalSandbox(Sandbox):
    """Host-direct sandbox. Reads/writes the host filesystem with no isolation."""

    def __init__(self, id: str = "local"):
        super().__init__(id)

    @staticmethod
    def _shell_name(shell: str) -> str:
        return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()

    @staticmethod
    def _is_powershell(shell: str) -> bool:
        return LocalSandbox._shell_name(shell) in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}

    @staticmethod
    def _is_cmd_shell(shell: str) -> bool:
        return LocalSandbox._shell_name(shell) in {"cmd", "cmd.exe"}

    @staticmethod
    def _find_first_available_shell(candidates: tuple[str, ...]) -> str | None:
        for shell in candidates:
            if os.path.isabs(shell):
                if os.path.isfile(shell) and os.access(shell, os.X_OK):
                    return shell
                continue
            shell_from_path = shutil.which(shell)
            if shell_from_path is not None:
                return shell_from_path
        return None

    @staticmethod
    def _get_shell() -> str:
        shell = LocalSandbox._find_first_available_shell(("/bin/zsh", "/bin/bash", "/bin/sh", "sh"))
        if shell is not None:
            return shell
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            shell = LocalSandbox._find_first_available_shell(
                (
                    "pwsh",
                    "pwsh.exe",
                    "powershell",
                    "powershell.exe",
                    ntpath.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                    "cmd.exe",
                )
            )
            if shell is not None:
                return shell
            raise RuntimeError("No suitable shell executable found.")
        raise RuntimeError("No suitable shell executable found.")

    def execute_command(self, command: str, *, cwd: str | None = None) -> str:
        shell = self._get_shell()
        if os.name == "nt" and self._is_powershell(shell):
            args = [shell, "-NoProfile", "-Command", command]
        elif os.name == "nt" and self._is_cmd_shell(shell):
            args = [shell, "/c", command]
        else:
            args = [shell, "-c", command]
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=cwd,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nStd Error:\n{result.stderr}" if output else result.stderr
        if result.returncode != 0:
            output += f"\nExit Code: {result.returncode}"
        return output if output else "(no output)"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        return list_dir(path, max_depth)

    def read_file(self, path: str) -> str:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise type(e)(e.errno, e.strerror, path) from None

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise type(e)(e.errno, e.strerror, path) from None

    def update_file(self, path: str, content: bytes) -> None:
        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
        except OSError as e:
            raise type(e)(e.errno, e.strerror, path) from None

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        return find_glob_matches(Path(path), pattern, include_dirs=include_dirs, max_results=max_results)

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        return find_grep_matches(
            Path(path),
            pattern,
            glob_pattern=glob,
            literal=literal,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )


# ── Singleton ───────────────────────────────────────────────────────────

_singleton: LocalSandbox | None = None


def get_sandbox() -> Sandbox:
    """Return the process-level Sandbox singleton."""
    global _singleton
    if _singleton is None:
        _singleton = LocalSandbox()
    return _singleton


def reset_sandbox_for_tests() -> None:
    """Clear the singleton — for unit tests only."""
    global _singleton
    _singleton = None


def set_sandbox_for_tests(sandbox: Sandbox) -> None:
    """Inject a custom Sandbox — for unit tests only."""
    global _singleton
    _singleton = sandbox  # type: ignore[assignment]
