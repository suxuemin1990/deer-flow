"""Module-level store registry for non-Request contexts.

Mirrors :mod:`deerflow.runtime.checkpointer_singleton`. The gateway's
``app.state.store`` is registered here at lifespan so the workflow
platform's ``start_workflow`` tool (which doesn't see a Request) can
record child workflow thread metadata against the parent chat thread.

Store may be ``None`` in some deployments (the gateway treats store as
optional); :func:`get_default_store` returns ``None`` in that case
rather than raising.
"""

from __future__ import annotations

from typing import Any

_default: Any = None


def set_default_store(store: Any) -> None:
    """Register the process-wide default store. Called from gateway lifespan."""
    global _default
    _default = store


def get_default_store() -> Any:
    """Return the registered default store (or ``None`` if not configured).

    Note:
        Unlike checkpointer_singleton, this getter does NOT raise on
        missing store — store is optional in some deployments. Callers
        must handle the ``None`` case.
    """
    return _default


def reset_default_store() -> None:
    """Clear the registered default. Test-only helper."""
    global _default
    _default = None
