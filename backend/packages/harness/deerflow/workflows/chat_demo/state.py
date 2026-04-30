"""ChatDemo state — composes WorkflowChatStateMixin for bidirectional chat."""

from __future__ import annotations

from typing import Annotated, NotRequired

from deerflow.workflows.base_state import WorkflowBaseState, WorkflowChatStateMixin


def _merge_list(existing: list | None, new: list | None) -> list:
    if existing is None:
        return new or []
    if new is None:
        return existing
    return existing + new


class ChatDemoState(WorkflowBaseState, WorkflowChatStateMixin):
    task_name: str
    max_rounds: int
    current_round: NotRequired[int]
    history: Annotated[list[dict], _merge_list]
    report_markdown: NotRequired[str]
    is_done: NotRequired[bool]
