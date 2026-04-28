"""Platform-reserved fields every workflow's state must carry.

Workflows compose this with their own business fields::

    class YoloExploreState(WorkflowBaseState):
        task_name: str
        max_rounds: int
        ...

The platform reads ``_parent_thread_id`` (set by start_workflow tool) and
``_error`` (set by background runner on exception).

**Hints are NOT here.** Earlier iterations stored ``_hints`` as a state
channel, but writing to it via ``aupdate_state`` while the workflow runs
created sibling-fork checkpoints that the running pregel overwrote on the
next tick — hints disappeared silently. Hints now live in
:mod:`deerflow.workflows.hints_inbox` (process-local, no checkpoint
involvement). Workflow nodes drain them via ``pop_hints(thread_id)``.
"""

from __future__ import annotations

from typing import TypedDict


class WorkflowBaseState(TypedDict, total=False):
    _parent_thread_id: str
    _error: str
