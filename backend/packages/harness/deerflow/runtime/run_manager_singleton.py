"""Module-level RunManager registry for non-Request contexts.

Mirror of :mod:`deerflow.runtime.checkpointer_singleton`. Background workflow
tasks need to know whether a parent thread has an in-flight run before they
emit a system message — otherwise the emit forks the parent's checkpoint
chain and gets overwritten by the still-streaming agent.

Tests can install a fake via :func:`set_default_run_manager` and clear with
:func:`reset_default_run_manager`. Use :func:`try_get_default_run_manager`
when the absence of a manager should not raise (e.g. unit tests that exercise
emit code without bootstrapping the gateway lifespan).
"""

from __future__ import annotations

from deerflow.runtime.runs.manager import RunManager

_default: RunManager | None = None


def set_default_run_manager(manager: RunManager) -> None:
    """Register the process-wide default RunManager."""
    global _default
    _default = manager


def get_default_run_manager() -> RunManager:
    """Return the registered default RunManager.

    Raises:
        RuntimeError: when no manager has been registered.
    """
    if _default is None:
        raise RuntimeError(
            "No default run manager registered. Call set_default_run_manager "
            "from gateway lifespan or test setup."
        )
    return _default


def try_get_default_run_manager() -> RunManager | None:
    """Return the registered RunManager or ``None`` if unset.

    Used by code paths that should degrade gracefully when run outside the
    gateway (e.g. unit tests, langgraph dev mode).
    """
    return _default


def reset_default_run_manager() -> None:
    """Clear the registered default. Test-only helper."""
    global _default
    _default = None
