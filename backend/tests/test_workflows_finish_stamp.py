"""Tests for the recent_workflow_finish_at parent-metadata stamper."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_stamp_writes_iso_timestamp(monkeypatch):
    import deerflow.runtime.store_singleton as ss
    from deerflow.workflows.finish_stamp import stamp_parent_finish

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)

    parent = "p-1"
    # Pre-create the parent record (mirrors how chat threads exist).
    from app.gateway.routers.threads import _store_upsert
    await _store_upsert(store, parent, metadata={})

    await stamp_parent_finish(parent)

    rec = (await store.aget(("threads",), parent)).value
    ts = rec["metadata"]["recent_workflow_finish_at"]
    assert ts.endswith("+00:00") or ts.endswith("Z")


@pytest.mark.asyncio
async def test_stamp_is_monotonic(monkeypatch):
    """Two stamps in a row must leave the larger timestamp in metadata."""
    import deerflow.runtime.store_singleton as ss
    from deerflow.workflows.finish_stamp import stamp_parent_finish

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)

    parent = "p-2"
    from app.gateway.routers.threads import _store_upsert
    await _store_upsert(store, parent, metadata={
        "recent_workflow_finish_at": "2099-01-01T00:00:00+00:00",  # far future
    })

    await stamp_parent_finish(parent)

    rec = (await store.aget(("threads",), parent)).value
    # The pre-existing far-future stamp must survive (now() is smaller).
    assert rec["metadata"]["recent_workflow_finish_at"] == "2099-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_stamp_swallows_missing_store(monkeypatch):
    """No store registered = no-op, no exception."""
    import deerflow.runtime.store_singleton as ss
    from deerflow.workflows.finish_stamp import stamp_parent_finish

    monkeypatch.setattr(ss, "get_default_store", lambda: None)
    await stamp_parent_finish("anything")  # must not raise


@pytest.mark.asyncio
async def test_stamp_creates_record_if_missing(monkeypatch):
    """If parent has no store record yet, stamp creates one with the timestamp."""
    import deerflow.runtime.store_singleton as ss
    from deerflow.workflows.finish_stamp import stamp_parent_finish

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)

    await stamp_parent_finish("brand-new")

    rec = (await store.aget(("threads",), "brand-new"))
    assert rec is not None
    assert "recent_workflow_finish_at" in rec.value["metadata"]
