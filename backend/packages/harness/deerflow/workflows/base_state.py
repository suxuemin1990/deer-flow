"""Platform-reserved fields every workflow's state must carry.

Workflows compose this with their own business fields::

    class YoloExploreState(WorkflowBaseState):
        task_name: str
        max_rounds: int
        ...

The platform reads ``_parent_thread_id`` (set by start_workflow tool),
``_hints`` (set by inject_hint tool), and ``_error`` (set by background
runner on exception).
"""

from __future__ import annotations

from typing import Annotated, TypedDict


def hints_reducer(
    existing: list[str] | None,
    new: list[str] | None,
) -> list[str]:
    """Append new hints; explicit empty list from a node clears the inbox."""
    if new is None:
        return existing or []
    if new == []:
        return []
    return (existing or []) + new


class WorkflowBaseState(TypedDict, total=False):
    _parent_thread_id: str
    _hints: Annotated[list[str], hints_reducer]
    _error: str
