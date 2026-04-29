"""WorkflowChatStateMixin contributes a `messages` add_messages channel."""

from __future__ import annotations

from typing import get_type_hints


def test_workflow_chat_state_mixin_declares_messages_channel():
    from deerflow.workflows.base_state import WorkflowChatStateMixin

    hints = get_type_hints(WorkflowChatStateMixin, include_extras=True)
    assert "messages" in hints, (
        "WorkflowChatStateMixin must declare a `messages` channel that "
        "workflows opting into chat compose into their state."
    )


def test_workflow_chat_state_mixin_uses_add_messages_reducer():
    """The `messages` annotation must include the langgraph add_messages reducer."""
    from typing import get_args

    from langgraph.graph.message import add_messages

    from deerflow.workflows.base_state import WorkflowChatStateMixin

    hints = get_type_hints(WorkflowChatStateMixin, include_extras=True)
    annotated = hints["messages"]
    args = get_args(annotated)
    assert add_messages in args, (
        f"messages annotation must include add_messages reducer, got {args!r}"
    )
