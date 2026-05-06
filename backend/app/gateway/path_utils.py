"""Shared path resolution for thread artifact paths."""

import logging
from pathlib import Path

from fastapi import HTTPException

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

_LEGACY_PREFIX = "mnt/user-data/"


def resolve_thread_artifact_path(thread_id: str, path: str) -> Path:
    """Resolve a thread-scoped artifact URL path to a host file path.

    Accepts both the new short form (``uploads/foo.pdf``) and the legacy form
    (``mnt/user-data/uploads/foo.pdf``). The legacy prefix is stripped
    transparently so URLs already rendered into older chat messages keep
    working.

    Args:
        thread_id: The thread ID.
        path: The artifact path component from the URL (no leading slash).

    Returns:
        The resolved filesystem path.

    Raises:
        HTTPException(403): If a path-traversal attempt is detected.
    """
    stripped = path.lstrip("/")
    if stripped.startswith(_LEGACY_PREFIX):
        stripped = stripped[len(_LEGACY_PREFIX) :]
        logger.debug("artifact url legacy prefix stripped: %s", stripped)

    user_data = get_paths().sandbox_user_data_dir(thread_id).resolve()

    # Absolute host path form: ``present_files`` stores absolute host paths in
    # ``thread.values.artifacts``; the frontend concatenates them onto the
    # endpoint URL, producing paths like ``data/.../user-data/outputs/foo``
    # (the leading ``/`` was consumed as the URL separator). If the path
    # re-prepended with ``/`` resolves to a location inside this thread's
    # user_data dir, treat it as already absolute.
    abs_candidate = Path("/" + stripped).resolve()
    try:
        abs_candidate.relative_to(user_data)
    except ValueError:
        pass
    else:
        return abs_candidate

    target = (user_data / stripped).resolve()
    try:
        target.relative_to(user_data)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path traversal detected") from exc
    return target
