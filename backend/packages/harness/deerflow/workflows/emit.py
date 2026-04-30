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
    additional_kwargs: dict | None = None,
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

    Args:
        parent_thread_id: thread to append to.
        content: AIMessage body.
        checkpointer: shared checkpointer.
        additional_kwargs: optional metadata attached to the AIMessage. The
            workflow runner uses this to mark messages with
            ``workflow_done.child_thread_id``/``workflow_cancelled``/
            ``workflow_failed`` so DELETE on a child thread can scrub the
            corresponding marker from the parent's history.

    Note:
        LangGraph's ``aupdate_state`` silently creates a fresh checkpoint
        when no prior checkpoint exists for ``parent_thread_id``. A wrong
        thread id therefore won't raise — callers that need strict
        "must exist" semantics must validate the id themselves.
    """
    appender = _build_message_appender(checkpointer)
    msg = AIMessage(
        content=content,
        additional_kwargs=dict(additional_kwargs) if additional_kwargs else {},
    )
    await appender.aupdate_state(
        config={"configurable": {"thread_id": parent_thread_id}},
        values={"messages": [msg]},
    )


async def inject_user_message_to_workflow(
    child_thread_id: str,
    content: str,
    *,
    spec,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Append a HumanMessage to a workflow child thread.

    Routing depends on whether the child currently has a running task:

    - **Running** (``child_thread_id in _BG_TASKS``): push to
      :mod:`hints_inbox`. The running workflow's loop node drains
      it next tick and emits a HumanMessage via its node return,
      so ``add_messages`` reducer merges cleanly. We CANNOT use
      ``aupdate_state`` here — it commits a sibling checkpoint that
      the running pregel's next step overwrites (Bug 5).

    - **Terminal**: write directly via ``aupdate_state``. No running
      task means no race; this is the simple path used to keep
      bidirectional chat working after completion.

    Why we use the caller-supplied workflow spec for the terminal
    branch: SQLite checkpointer only serializes channels declared
    on the schema being used to write. Writing HumanMessage via a
    graph compiled against ``ThreadState`` (channels = messages,
    title, thread_data, artifacts) silently drops every
    workflow-specific field on the next checkpoint — wiping the
    workflow's state. By using ``spec.factory(checkpointer=...)``,
    the appender graph has the workflow's real TypedDict and every
    channel survives.

    Caveat (single-process assumption): ``_BG_TASKS`` is in-memory
    per gateway worker. Multi-worker deployments would route a
    POST landing on a non-owning worker through the wrong branch.
    Gateway is currently single-process by deployment convention.

    Args:
        child_thread_id: Target child workflow thread.
        content: Free-text user instruction.
        spec: The :class:`WorkflowSpec` of the workflow on
            ``child_thread_id``. The caller is responsible for looking
            it up; passing a spec from a different workflow would
            corrupt state.
        checkpointer: Shared checkpointer.
    """
    from langchain_core.messages import HumanMessage

    # Lazy import to avoid a startup cycle:
    # workflows.tools imports workflows.emit (start_workflow), so
    # emit at module-load can't import tools.
    from deerflow.workflows import hints_inbox
    from deerflow.workflows.tools import _BG_TASKS

    if child_thread_id in _BG_TASKS:
        # Running: side-channel.
        await hints_inbox.push(child_thread_id, content)
        return

    # Terminal: direct write is safe.
    appender = spec.factory(checkpointer=checkpointer)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": child_thread_id}},
        values={"messages": [HumanMessage(content=content)]},
        as_node="__start__",
    )
