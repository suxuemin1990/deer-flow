"""Platform-reserved fields every workflow's state must carry.

Workflows compose this with their own business fields::

    class MyFlowState(WorkflowBaseState):
        task_name: str
        max_rounds: int
        ...

The platform reads ``_parent_thread_id`` (set by start_workflow tool) and
``_error`` (set by background runner on exception).

**Bidirectional chat (opt-in):** workflows that want to receive user
injection through the UI / inject_hint tool, and reply with AIMessages,
should additionally compose :class:`WorkflowChatStateMixin`::

    class MyFlowState(WorkflowBaseState, WorkflowChatStateMixin):
        ...

and the corresponding spec must declare ``accepts_chat: True``.

Hints flow through one of two paths depending on workflow state:

- **Running**: POST handler pushes to :mod:`hints_inbox`; the
  workflow's loop node drains and emits HumanMessages via node
  return so ``add_messages`` merges cleanly without overwrite race.
- **Terminal**: direct ``aupdate_state`` write to the ``messages``
  channel (no race because no running task).

Both paths land in ``state['messages']`` from the workflow author's
point of view; they need to filter by ``_seen_msg_ids`` to avoid
re-feeding the inner LLM on every tick.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class WorkflowBaseState(TypedDict, total=False):
    _parent_thread_id: str
    _error: str


class WorkflowChatStateMixin(TypedDict, total=False):
    """Opt-in mixin for workflows that accept user-injected chat messages.

    ``messages``: bidirectional chat history. HumanMessages come from
        user injection; AIMessages come from workflow nodes' returns.
    ``_seen_msg_ids``: workflow-author-owned set of message ids already
        consumed; used to avoid re-feeding the same hint into the inner
        LLM each tick. The framework neither writes nor reads this.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    _seen_msg_ids: set[str]
