"""Tests for thread search filtering out child workflow threads.

Workflow child threads run on the same checkpointer as user chat threads,
so a naive /threads/search returns them — they show up as "Untitled"
entries in the chat sidebar. The list must filter them out using the
parent threads' metadata.child_workflow_threads as the source of truth.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


def _make_request(store, checkpointer):
    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = checkpointer
    return req


@pytest.mark.asyncio
async def test_search_filters_out_child_workflow_threads():
    """Threads listed in any parent's metadata.child_workflow_threads
    must not appear in /threads/search results."""
    from app.gateway.routers.threads import (
        ThreadSearchRequest,
        _store_upsert,
        search_threads,
    )

    store = InMemoryStore()
    cp = InMemorySaver()

    # Parent thread with two child workflow threads recorded.
    await _store_upsert(
        store,
        "parent-1",
        values={"title": "user chat"},
        metadata={
            "child_workflow_threads": [
                {"thread_id": "child-A", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
                {"thread_id": "child-B", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
            ],
        },
    )
    # The children themselves were also upserted into the store
    # (workflow_background writes through the checkpointer; in real
    # deployment these can also surface via Phase 2 scan).
    await _store_upsert(store, "child-A", metadata={})
    await _store_upsert(store, "child-B", metadata={})
    # Plus a normal user chat thread that has no children.
    await _store_upsert(store, "parent-2", values={"title": "another chat"})

    body = ThreadSearchRequest(limit=50)
    req = _make_request(store, cp)
    results = await search_threads(body, request=req)

    ids = [r.thread_id for r in results]
    assert "parent-1" in ids
    assert "parent-2" in ids
    assert "child-A" not in ids, "child workflow thread leaked into search"
    assert "child-B" not in ids, "child workflow thread leaked into search"


@pytest.mark.asyncio
async def test_search_handles_parent_without_children_metadata():
    """Parent thread with no child_workflow_threads key must still be returned."""
    from app.gateway.routers.threads import (
        ThreadSearchRequest,
        _store_upsert,
        search_threads,
    )

    store = InMemoryStore()
    cp = InMemorySaver()
    await _store_upsert(store, "p", values={"title": "plain chat"})

    body = ThreadSearchRequest(limit=50)
    req = _make_request(store, cp)
    results = await search_threads(body, request=req)
    assert [r.thread_id for r in results] == ["p"]


@pytest.mark.asyncio
async def test_search_handles_malformed_children_metadata():
    """If child_workflow_threads has unexpected shape, search must not crash;
    it returns the parent and treats the unparseable entries as not-children."""
    from app.gateway.routers.threads import (
        ThreadSearchRequest,
        _store_upsert,
        search_threads,
    )

    store = InMemoryStore()
    cp = InMemorySaver()
    await _store_upsert(
        store,
        "p",
        values={"title": "x"},
        metadata={
            "child_workflow_threads": [
                "just-a-string",  # malformed: not a dict
                {"name": "demo-flow"},  # malformed: missing thread_id
                {"thread_id": "good-child", "name": "demo-flow"},
            ],
        },
    )
    await _store_upsert(store, "good-child", metadata={})

    body = ThreadSearchRequest(limit=50)
    req = _make_request(store, cp)
    results = await search_threads(body, request=req)
    ids = [r.thread_id for r in results]
    assert "p" in ids
    assert "good-child" not in ids
