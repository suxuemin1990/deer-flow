"""DELETE /threads/{child_tid} must clean up parent references.

When a user deletes a *child* workflow thread (via the workflow-hub trash
icon → ``DELETE /api/threads/{child}``), the parent chat thread keeps
three persistent references that become dangling:

1. ``metadata.child_workflow_threads`` — the entry referring to the deleted
   child must be removed.
2. The ``start_workflow`` ToolMessage — carries
   ``additional_kwargs.workflow_link.child_thread_id`` pointing at the
   deleted child; the inline workflow_link card in the parent chat would
   link to a 404 page.
3. The ``[workflow:NAME] done`` AIMessage emitted via
   ``emit_to_parent_thread`` — also references the deleted child via
   ``additional_kwargs.workflow_done.child_thread_id``.

This is the reverse-direction cleanup; the existing forward direction
(parent delete cascading into children) is covered by
``test_threads_delete_cascades_children.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.routers import threads
from deerflow.config.paths import Paths


def _build_app(store, checkpointer):
    app = FastAPI()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.include_router(threads.router)
    return app


async def _seed_parent_with_two_children(
    *, store, cp, parent_id: str, child_a: str, child_b: str
) -> tuple[str, str, str, str]:
    """Write a parent thread that holds workflow links to two children.

    Returns the message ids for (tool_a, ai_a, tool_b, ai_b) so the test
    can assert which ones survive after delete.
    """
    from langgraph.graph import END, START, StateGraph

    from deerflow.agents.thread_state import ThreadState

    g = StateGraph(ThreadState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    appender = g.compile(checkpointer=cp)
    cfg = {"configurable": {"thread_id": parent_id}}

    tool_a = ToolMessage(
        content=f"started {child_a}",
        tool_call_id="call-a",
        id="msg-tool-a",
        additional_kwargs={
            "element": "workflow_link",
            "workflow_link": {
                "child_thread_id": child_a,
                "name": "demo-flow",
                "url": f"/workspace/workflows/{child_a}",
            },
        },
    )
    ai_a = AIMessage(
        content=f"[workflow:demo-flow] done\n\nReport for {child_a}",
        id="msg-ai-a",
        additional_kwargs={
            "workflow_done": {"child_thread_id": child_a, "name": "demo-flow"},
        },
    )
    tool_b = ToolMessage(
        content=f"started {child_b}",
        tool_call_id="call-b",
        id="msg-tool-b",
        additional_kwargs={
            "element": "workflow_link",
            "workflow_link": {
                "child_thread_id": child_b,
                "name": "demo-flow",
                "url": f"/workspace/workflows/{child_b}",
            },
        },
    )
    ai_b = AIMessage(
        content=f"[workflow:demo-flow] done\n\nReport for {child_b}",
        id="msg-ai-b",
        additional_kwargs={
            "workflow_done": {"child_thread_id": child_b, "name": "demo-flow"},
        },
    )
    user = HumanMessage(content="please run two demo-flows", id="msg-user-1")
    await appender.aupdate_state(
        config=cfg,
        values={"messages": [user, tool_a, ai_a, tool_b, ai_b]},
    )

    await threads._store_upsert(
        store,
        parent_id,
        values={"title": "user chat"},
        metadata={
            "child_workflow_threads": [
                {"thread_id": child_a, "name": "demo-flow",
                 "started_at": "2026-01-01T00:00:00Z"},
                {"thread_id": child_b, "name": "demo-flow",
                 "started_at": "2026-01-01T00:00:00Z"},
            ],
        },
    )
    return ("msg-tool-a", "msg-ai-a", "msg-tool-b", "msg-ai-b")


async def _write_child_checkpoint(cp: InMemorySaver, thread_id: str) -> None:
    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    await cp.aput(
        cfg,
        {
            "v": 1,
            "id": f"cp-{thread_id}",
            "ts": "2026-01-01T00:00:00Z",
            "channel_values": {"x": 1},
            "channel_versions": {},
            "versions_seen": {},
        },
        {"source": "test"},
        {},
    )


async def _read_parent_messages(cp, parent_id):
    from langgraph.graph import END, START, StateGraph

    from deerflow.agents.thread_state import ThreadState

    g = StateGraph(ThreadState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    appender = g.compile(checkpointer=cp)
    state = await appender.aget_state({"configurable": {"thread_id": parent_id}})
    return list((state.values or {}).get("messages") or [])


@pytest.mark.asyncio
async def test_delete_child_strips_parent_metadata_and_messages(tmp_path):
    paths = Paths(tmp_path)
    store = InMemoryStore()
    cp = InMemorySaver()

    parent_id = "parent-1"
    child_a = "child-A"
    child_b = "child-B"

    await _seed_parent_with_two_children(
        store=store, cp=cp,
        parent_id=parent_id, child_a=child_a, child_b=child_b,
    )
    await threads._store_upsert(store, child_a, metadata={})
    await threads._store_upsert(store, child_b, metadata={})
    await _write_child_checkpoint(cp, child_a)
    await _write_child_checkpoint(cp, child_b)
    paths.sandbox_work_dir(child_a).mkdir(parents=True, exist_ok=True)
    paths.sandbox_work_dir(child_b).mkdir(parents=True, exist_ok=True)

    app = _build_app(store, cp)
    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            r = client.delete(f"/api/threads/{child_a}")
    assert r.status_code == 200

    # Child A is gone everywhere.
    assert await store.aget(threads.THREADS_NS, child_a) is None
    assert (
        await cp.aget_tuple({"configurable": {"thread_id": child_a, "checkpoint_ns": ""}})
        is None
    )

    # Parent metadata: only child_b remains.
    parent_rec = await store.aget(threads.THREADS_NS, parent_id)
    assert parent_rec is not None
    children = (parent_rec.value.get("metadata") or {}).get(
        "child_workflow_threads"
    )
    assert isinstance(children, list)
    remaining_tids = [
        e["thread_id"] for e in children
        if isinstance(e, dict) and e.get("thread_id")
    ]
    assert remaining_tids == [child_b], (
        f"parent metadata still references deleted child_a: {children}"
    )

    # Parent messages: child_a's tool/ai messages gone, child_b's intact.
    msgs = await _read_parent_messages(cp, parent_id)
    msg_ids = [m.id for m in msgs if getattr(m, "id", None)]
    assert "msg-tool-a" not in msg_ids, "workflow_link ToolMessage for child_a leaked"
    assert "msg-ai-a" not in msg_ids, "workflow_done AIMessage for child_a leaked"
    assert "msg-tool-b" in msg_ids, "child_b's ToolMessage was wrongly removed"
    assert "msg-ai-b" in msg_ids, "child_b's AIMessage was wrongly removed"
    assert "msg-user-1" in msg_ids, "user message was wrongly removed"

    # Child B untouched.
    assert await store.aget(threads.THREADS_NS, child_b) is not None
    assert (
        await cp.aget_tuple({"configurable": {"thread_id": child_b, "checkpoint_ns": ""}})
        is not None
    )


@pytest.mark.asyncio
async def test_delete_non_child_thread_does_not_touch_other_parents(tmp_path):
    """Deleting a thread that is not anyone's child must not modify other
    parents' metadata or messages — sanity check that the scrub is gated on
    membership."""
    paths = Paths(tmp_path)
    store = InMemoryStore()
    cp = InMemorySaver()

    other_parent = "other-parent"
    other_child = "other-child"
    standalone = "standalone-thread"

    await _seed_parent_with_two_children(
        store=store, cp=cp,
        parent_id=other_parent, child_a=other_child, child_b="unused-child",
    )
    await threads._store_upsert(store, standalone, metadata={})
    await _write_child_checkpoint(cp, standalone)

    app = _build_app(store, cp)
    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            r = client.delete(f"/api/threads/{standalone}")
    assert r.status_code == 200

    # other_parent's metadata still has both children.
    rec = await store.aget(threads.THREADS_NS, other_parent)
    assert rec is not None
    kept = [
        e["thread_id"] for e in
        (rec.value.get("metadata") or {}).get("child_workflow_threads") or []
        if isinstance(e, dict)
    ]
    assert sorted(kept) == sorted([other_child, "unused-child"])

    # other_parent's messages still has all 4 workflow refs.
    msgs = await _read_parent_messages(cp, other_parent)
    msg_ids = {m.id for m in msgs if getattr(m, "id", None)}
    assert {"msg-tool-a", "msg-ai-a", "msg-tool-b", "msg-ai-b"} <= msg_ids
