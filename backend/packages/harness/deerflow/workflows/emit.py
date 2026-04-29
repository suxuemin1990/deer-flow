"""Emit a message into another (parent) thread's checkpoint.

Uses LangGraph's standard ``aupdate_state`` so:
- the message becomes part of the thread's checkpoint history
- subscribers to ``/threads/{tid}/runs/stream`` see the update naturally
- we never bypass the checkpointer with raw SQL

A minimal noop graph is compiled per call against ``ThreadState`` (the schema
the lead_agent thread already uses) so ``aupdate_state`` writes a checkpoint
that retains every ThreadState channel — using a smaller schema like
``MessagesState`` causes persistent checkpointers (sqlite) to drop unknown
channels (``title``, ``thread_data``, ``artifacts``).

This couples ``workflows.emit`` to ``agents.thread_state.ThreadState``, which
is acceptable: emit currently only targets lead_agent threads, and the
alternative (passing schema in from every caller) buys nothing today.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph


def _build_message_appender(checkpointer: BaseCheckpointSaver):
    # Lazy import: ``deerflow.agents.thread_state`` triggers ``agents/__init__``,
    # which transitively imports tool builtins → workflow tools → back here,
    # creating an import cycle when ``workflows.background`` is loaded
    # standalone (e.g. from a fresh test process). Deferring the import to
    # the first emit call keeps module-load free of agents-package side effects.
    from deerflow.agents.thread_state import ThreadState

    g = StateGraph(ThreadState)
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
    """Append an AIMessage to the parent thread's checkpoint.

    Why AIMessage and not SystemMessage:
        - The frontend's groupMessages() only renders human/tool/ai message
          types; system messages are silently dropped.
        - Message-channel forwarders (Slack/Discord/Feishu) treat assistant
          content as the natural "agent reply" payload.
        - Workflow completion notices semantically belong to the agent's
          turn — the agent is the one telling the user "the workflow you
          asked for finished and here's the report".

    Note:
        LangGraph's ``aupdate_state`` silently creates a fresh checkpoint
        when no prior checkpoint exists for ``parent_thread_id``. A wrong
        thread id therefore won't raise — callers that need strict
        "must exist" semantics must validate the id themselves.
    """
    appender = _build_message_appender(checkpointer)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": parent_thread_id}},
        values={"messages": [AIMessage(content=content)]},
    )
