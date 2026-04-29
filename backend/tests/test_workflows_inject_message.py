"""Tests for inject_user_message_to_workflow — append HumanMessage to a
running workflow's messages channel using the workflow's own state schema
so SQLite checkpointer doesn't drop business fields."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver


def _make_demo_spec():
    """Build a real WorkflowSpec for demo-flow (uses messages channel)."""
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.registry import WorkflowSpec

    return WorkflowSpec(
        name="demo-flow",
        description="x",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
        progress_fields=["current_round", "max_rounds"],
        accepts_chat=True,
    )


@pytest.mark.asyncio
async def test_inject_user_message_appends_human_message_to_child_thread():
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    spec = _make_demo_spec()
    child_tid = "child-1"

    await inject_user_message_to_workflow(
        child_tid, "use dropout", spec=spec, checkpointer=cp,
    )

    appender = spec.factory(checkpointer=cp)
    state = await appender.aget_state({"configurable": {"thread_id": child_tid}})
    msgs = state.values.get("messages") or []
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "use dropout"


@pytest.mark.asyncio
async def test_inject_user_message_appends_to_existing_messages():
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    spec = _make_demo_spec()
    child_tid = "child-2"

    # Seed an existing AIMessage via the same workflow graph (so the
    # other channels stay intact).
    appender = spec.factory(checkpointer=cp)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": child_tid}},
        values={"messages": [AIMessage(content="hello")]},
    )

    await inject_user_message_to_workflow(
        child_tid, "ok", spec=spec, checkpointer=cp,
    )

    state = await appender.aget_state({"configurable": {"thread_id": child_tid}})
    msgs = state.values.get("messages") or []
    assert len(msgs) == 2
    assert isinstance(msgs[0], AIMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert msgs[1].content == "ok"


@pytest.mark.asyncio
async def test_inject_preserves_workflow_business_fields():
    """Regression: writing through ThreadState's noop graph drops every
    workflow-specific channel (current_round, max_rounds, history, ...)
    on the next checkpoint write, wiping the workflow's state. Using the
    workflow's own graph as the appender must NOT drop these."""
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    spec = _make_demo_spec()
    child_tid = "child-3"

    # Run one round to populate business fields.
    graph = spec.factory(checkpointer=cp)
    await graph.ainvoke(
        {"task_name": "t", "max_rounds": 3, "_parent_thread_id": "p"},
        config={"configurable": {"thread_id": child_tid}},
    )
    state_before = await graph.aget_state({"configurable": {"thread_id": child_tid}})
    assert "current_round" in state_before.values
    assert "max_rounds" in state_before.values
    before_round = state_before.values["current_round"]

    # Inject — must not wipe current_round / max_rounds / history.
    await inject_user_message_to_workflow(
        child_tid, "hint after running", spec=spec, checkpointer=cp,
    )

    state_after = await graph.aget_state({"configurable": {"thread_id": child_tid}})
    assert state_after.values.get("current_round") == before_round
    assert state_after.values.get("max_rounds") == 3
    assert state_after.values.get("task_name") == "t"
    msgs = state_after.values.get("messages") or []
    human = [m for m in msgs if isinstance(m, HumanMessage)]
    assert len(human) >= 1
    assert any(m.content == "hint after running" for m in human)
