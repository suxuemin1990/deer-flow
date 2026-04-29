"""Tests that DELETE /threads/{tid} cascades to its child workflow threads.

A user chat thread can spawn child workflow threads (recorded in the parent's
``metadata.child_workflow_threads``). When the user deletes the parent chat,
the children must be cleaned up too — otherwise their checkpoints, store
records, and filesystem dirs leak forever (they're hidden from
/threads/search by ``_filter_workflow_child_threads``, so they become
invisible orphans).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


async def _write_checkpoint(cp: InMemorySaver, thread_id: str) -> None:
    """Write a minimal checkpoint so adelete_thread has something to remove."""
    cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = {
        "v": 1,
        "id": f"cp-{thread_id}",
        "ts": "2026-01-01T00:00:00Z",
        "channel_values": {"x": 1},
        "channel_versions": {},
        "versions_seen": {},
    }
    await cp.aput(cfg, checkpoint, {"source": "test"}, {})


@pytest.mark.asyncio
async def test_delete_parent_thread_removes_child_workflow_threads(tmp_path):
    paths = Paths(tmp_path)
    store = InMemoryStore()
    cp = InMemorySaver()

    parent_id = "parent-1"
    child_a = "child-A"
    child_b = "child-B"

    # Parent record names two children.
    await threads._store_upsert(
        store,
        parent_id,
        values={"title": "user chat"},
        metadata={
            "child_workflow_threads": [
                {"thread_id": child_a, "name": "demo-flow", "started_at": "2026-01-01T00:00:00Z"},
                {"thread_id": child_b, "name": "demo-flow", "started_at": "2026-01-01T00:00:00Z"},
            ],
        },
    )
    # Children also have store records and checkpoints.
    await threads._store_upsert(store, child_a, metadata={})
    await threads._store_upsert(store, child_b, metadata={})
    await _write_checkpoint(cp, parent_id)
    await _write_checkpoint(cp, child_a)
    await _write_checkpoint(cp, child_b)

    # Children also have on-disk thread dirs.
    for tid in (parent_id, child_a, child_b):
        d = paths.sandbox_work_dir(tid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "marker.txt").write_text(tid, encoding="utf-8")

    app = _build_app(store, cp)
    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete(f"/api/threads/{parent_id}")

    assert response.status_code == 200
    assert response.json()["success"] is True

    # Parent gone everywhere.
    assert await store.aget(threads.THREADS_NS, parent_id) is None
    assert (
        await cp.aget_tuple({"configurable": {"thread_id": parent_id, "checkpoint_ns": ""}})
        is None
    )
    assert not paths.thread_dir(parent_id).exists()

    # Children must also be gone (this is the bug being fixed).
    for child in (child_a, child_b):
        assert await store.aget(threads.THREADS_NS, child) is None, f"{child} store record leaked"
        assert (
            await cp.aget_tuple({"configurable": {"thread_id": child, "checkpoint_ns": ""}})
            is None
        ), f"{child} checkpoint leaked"
        assert not paths.thread_dir(child).exists(), f"{child} fs dir leaked"


@pytest.mark.asyncio
async def test_delete_parent_with_no_children_metadata_still_works(tmp_path):
    """Parent without child_workflow_threads must delete normally (no regression)."""
    paths = Paths(tmp_path)
    store = InMemoryStore()
    cp = InMemorySaver()

    await threads._store_upsert(store, "p", values={"title": "x"})
    await _write_checkpoint(cp, "p")
    paths.sandbox_work_dir("p").mkdir(parents=True, exist_ok=True)

    app = _build_app(store, cp)
    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/p")

    assert response.status_code == 200
    assert await store.aget(threads.THREADS_NS, "p") is None
    assert not paths.thread_dir("p").exists()


@pytest.mark.asyncio
async def test_delete_parent_with_malformed_children_metadata_does_not_crash(tmp_path):
    """Malformed child entries (non-dict, missing thread_id) must be skipped."""
    paths = Paths(tmp_path)
    store = InMemoryStore()
    cp = InMemorySaver()

    await threads._store_upsert(
        store,
        "p",
        metadata={
            "child_workflow_threads": [
                "just-a-string",
                {"name": "demo-flow"},  # missing thread_id
                {"thread_id": "good-child", "name": "demo-flow"},
            ],
        },
    )
    await threads._store_upsert(store, "good-child", metadata={})
    await _write_checkpoint(cp, "good-child")

    app = _build_app(store, cp)
    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/p")

    assert response.status_code == 200
    assert await store.aget(threads.THREADS_NS, "good-child") is None


@pytest.mark.asyncio
async def test_delete_parent_continues_when_one_child_cleanup_fails(tmp_path):
    """If one child fails to clean (e.g. invalid id), the other children
    and the parent must still be cleaned up — best-effort cascade."""
    paths = Paths(tmp_path)
    store = InMemoryStore()
    cp = InMemorySaver()

    await threads._store_upsert(
        store,
        "p",
        metadata={
            "child_workflow_threads": [
                {"thread_id": "../bad", "name": "demo-flow"},  # invalid id
                {"thread_id": "ok-child", "name": "demo-flow"},
            ],
        },
    )
    await threads._store_upsert(store, "ok-child", metadata={})
    await _write_checkpoint(cp, "ok-child")

    app = _build_app(store, cp)
    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/p")

    assert response.status_code == 200
    # Good child cleaned up.
    assert await store.aget(threads.THREADS_NS, "ok-child") is None
    assert (
        await cp.aget_tuple({"configurable": {"thread_id": "ok-child", "checkpoint_ns": ""}})
        is None
    )
    # Parent gone.
    assert await store.aget(threads.THREADS_NS, "p") is None
