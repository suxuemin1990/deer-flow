"""Tests for emit_to_parent_thread."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_emit_appends_ai_message_so_frontend_renders_it():
    """Emit must produce an AIMessage, not SystemMessage.

    The frontend's groupMessages() in core/messages/utils.ts only handles
    type ∈ {human, tool, ai}. SystemMessage (type='system') is silently
    dropped from rendering. AIMessage also matches what message-channel
    forwarders (Slack/Discord/Feishu) expect for assistant-side content.
    """
    from langchain_core.messages import AIMessage, HumanMessage
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
    messages = state.values["messages"]
    contents = [m.content for m in messages]
    assert "[workflow:demo] done" in contents

    emitted = next(m for m in messages if m.content == "[workflow:demo] done")
    assert isinstance(emitted, AIMessage), (
        f"emit must produce AIMessage so frontend renders it; got {type(emitted).__name__}"
    )
    assert emitted.type == "ai"


@pytest.mark.asyncio
async def test_emit_creates_checkpoint_for_unknown_thread():
    """LangGraph's aupdate_state will create a fresh checkpoint if one doesn't exist."""
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.workflows.emit import emit_to_parent_thread

    saver = InMemorySaver()
    # Should not raise
    await emit_to_parent_thread("unknown-thread", "msg", checkpointer=saver)
