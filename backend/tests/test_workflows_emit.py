"""Tests for emit_to_parent_thread."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_emit_appends_system_message_to_parent_thread():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows.emit import emit_to_parent_thread

    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)

    parent_tid = "parent-1"
    cfg = {"configurable": {"thread_id": parent_tid}}
    await parent_graph.ainvoke({"messages": [HumanMessage(content="hi")]}, config=cfg)

    await emit_to_parent_thread(
        parent_tid,
        "[workflow:demo] done",
        checkpointer=saver,
    )

    state = await parent_graph.aget_state(cfg)
    contents = [m.content for m in state.values["messages"]]
    assert "[workflow:demo] done" in contents


@pytest.mark.asyncio
async def test_emit_creates_checkpoint_for_unknown_thread():
    """LangGraph's aupdate_state will create a fresh checkpoint if one doesn't exist."""
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.workflows.emit import emit_to_parent_thread

    saver = InMemorySaver()
    # Should not raise
    await emit_to_parent_thread("unknown-thread", "msg", checkpointer=saver)
