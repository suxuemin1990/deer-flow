"""Test the GET /api/threads/{tid}/children endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_children_endpoint_returns_metadata_when_present():
    from langgraph.store.memory import InMemoryStore

    from app.gateway.routers.threads import _store_upsert, list_thread_children

    store = InMemoryStore()
    parent_tid = "parent-1"
    child_meta = {
        "child_workflow_threads": [
            {"thread_id": "c-1", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
        ]
    }
    await _store_upsert(store, parent_tid, metadata=child_meta)

    result = await list_thread_children(parent_tid, store=store)
    assert result == {
        "children": [
            {"thread_id": "c-1", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
        ]
    }


@pytest.mark.asyncio
async def test_children_endpoint_returns_empty_when_no_record():
    from langgraph.store.memory import InMemoryStore

    from app.gateway.routers.threads import list_thread_children

    store = InMemoryStore()
    result = await list_thread_children("missing-thread", store=store)
    assert result == {"children": []}


@pytest.mark.asyncio
async def test_children_endpoint_returns_empty_when_store_none():
    from app.gateway.routers.threads import list_thread_children

    result = await list_thread_children("anything", store=None)
    assert result == {"children": []}


@pytest.mark.asyncio
async def test_children_endpoint_returns_empty_when_no_metadata_key():
    from langgraph.store.memory import InMemoryStore

    from app.gateway.routers.threads import _store_upsert, list_thread_children

    store = InMemoryStore()
    await _store_upsert(store, "no-children-thread")
    result = await list_thread_children("no-children-thread", store=store)
    assert result == {"children": []}
