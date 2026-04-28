"""Emit a message into another (parent) thread's checkpoint.

Uses LangGraph's standard ``aupdate_state`` so:
- the message becomes part of the thread's checkpoint history
- subscribers to ``/threads/{tid}/runs/stream`` see the update naturally
- we never bypass the checkpointer with raw SQL

A minimal MessagesState graph is compiled per call to obtain an updater
bound to the given checkpointer; this is cheap (StateGraph compile is
in-memory) and avoids needing the parent thread's actual graph factory.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph


def _build_message_appender(checkpointer: BaseCheckpointSaver):
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    return g.compile(checkpointer=checkpointer)


async def emit_to_parent_thread(
    parent_thread_id: str,
    content: str,
    *,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Append a SystemMessage to the parent thread's checkpoint.

    Note:
        LangGraph's ``aupdate_state`` silently creates a fresh checkpoint
        when no prior checkpoint exists for ``parent_thread_id``. A wrong
        thread id therefore won't raise — callers that need strict
        "must exist" semantics must validate the id themselves.
    """
    appender = _build_message_appender(checkpointer)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": parent_thread_id}},
        values={"messages": [SystemMessage(content=content)]},
    )
