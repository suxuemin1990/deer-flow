"""Module-level checkpointer registry for non-Request contexts.

Tools running inside the LangGraph agent loop don't get a FastAPI Request and
can't pull the checkpointer out of ``app.state``. This singleton lets gateway
register its long-lived checkpointer at startup so background tasks (e.g.
``start_demo_exploration``) can share it.

Tests can install a fake via :func:`set_default_checkpointer` and clear with
:func:`reset_default_checkpointer`.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver

_default: BaseCheckpointSaver | None = None


def set_default_checkpointer(checkpointer: BaseCheckpointSaver) -> None:
    """Register the process-wide default checkpointer."""
    global _default
    _default = checkpointer


def get_default_checkpointer() -> BaseCheckpointSaver:
    """Return the registered default checkpointer.

    Raises:
        RuntimeError: when no checkpointer has been registered yet.
    """
    if _default is None:
        raise RuntimeError(
            "No default checkpointer registered. Call set_default_checkpointer "
            "from gateway lifespan or test setup."
        )
    return _default


def reset_default_checkpointer() -> None:
    """Clear the registered default. Test-only helper."""
    global _default
    _default = None
