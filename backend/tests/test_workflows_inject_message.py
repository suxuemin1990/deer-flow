"""Tests for inject_user_message_to_workflow — append HumanMessage to a
running workflow's messages channel."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_inject_user_message_appends_human_message_to_child_thread():
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    child_tid = "child-1"

    await inject_user_message_to_workflow(
        child_tid, "use dropout", checkpointer=cp,
    )

    # Verify the HumanMessage landed in the child thread's messages channel.
    from deerflow.workflows.emit import _build_message_appender
    appender = _build_message_appender(cp)
    state = await appender.aget_state({"configurable": {"thread_id": child_tid}})
    msgs = state.values.get("messages") or []
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "use dropout"


@pytest.mark.asyncio
async def test_inject_user_message_appends_to_existing_messages():
    from deerflow.workflows.emit import (
        _build_message_appender,
        inject_user_message_to_workflow,
    )

    cp = MemorySaver()
    child_tid = "child-2"

    appender = _build_message_appender(cp)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": child_tid}},
        values={"messages": [AIMessage(content="hello")]},
    )

    await inject_user_message_to_workflow(child_tid, "ok", checkpointer=cp)

    state = await appender.aget_state({"configurable": {"thread_id": child_tid}})
    msgs = state.values.get("messages") or []
    assert len(msgs) == 2
    assert isinstance(msgs[0], AIMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert msgs[1].content == "ok"
