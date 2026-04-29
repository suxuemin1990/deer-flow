"""Tests for GET /api/workflows/all — cross-thread workflow aggregation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_workflows_hub_returns_parents_with_their_children():
    """A parent thread with two child workflows shows both in the tree."""
    from app.gateway.routers.workflows_hub import list_all_workflows

    # Build a fake Store + Checkpointer
    store = MagicMock()
    parent_record = {
        "thread_id": "p1",
        "title": "Discussion about training",
        "created_at": "2026-04-29T10:00:00+00:00",
        "metadata": {
            "child_workflow_threads": [
                {"thread_id": "c1", "name": "demo-flow",
                 "started_at": "2026-04-29T10:05:00+00:00"},
                {"thread_id": "c2", "name": "demo-flow",
                 "started_at": "2026-04-29T10:10:00+00:00"},
            ],
        },
    }
    item = MagicMock()
    item.value = parent_record
    item.key = "p1"
    store.asearch = AsyncMock(return_value=[item])

    # Checkpointer returns terminal state for c1, in-progress for c2
    cp = MagicMock()

    def make_tuple(values):
        t = MagicMock()
        t.checkpoint = {"channel_values": values}
        return t

    async def aget_tuple(config):
        cid = config["configurable"]["thread_id"]
        if cid == "c1":
            return make_tuple({
                "is_done": True, "current_round": 3, "max_rounds": 3,
                "report_markdown": "## Report\n...",
            })
        if cid == "c2":
            return make_tuple({
                "is_done": False, "current_round": 1, "max_rounds": 3,
            })
        return None

    cp.aget_tuple = AsyncMock(side_effect=aget_tuple)

    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = cp

    # Stub registry so demo-flow is known with progress_fields
    import deerflow.workflows.tools as wftools
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class _IS(BaseModel):
        pass

    spec = WorkflowSpec(
        name="demo-flow", description="x",
        factory=lambda **k: None, input_schema=_IS,
        done_field="is_done", report_field="report_markdown",
        progress_fields=["current_round", "max_rounds"],
    )
    fake_reg = WorkflowRegistry([spec], [])
    wftools._REGISTRY = fake_reg
    # Mark both as registered so they're recognized
    wftools._THREAD_TO_WORKFLOW = {"c1": "demo-flow", "c2": "demo-flow"}

    result = await list_all_workflows(req)

    assert "parents" in result
    assert len(result["parents"]) == 1
    parent = result["parents"][0]
    assert parent["thread_id"] == "p1"
    assert parent["title"] == "Discussion about training"
    assert len(parent["workflows"]) == 2

    by_id = {w["child_thread_id"]: w for w in parent["workflows"]}
    assert by_id["c1"]["status"] == "done"
    assert by_id["c1"]["report_preview"].startswith("## Report")
    assert by_id["c2"]["status"] == "running"
    assert by_id["c2"]["progress"] == {"current_round": 1, "max_rounds": 3}


@pytest.mark.asyncio
async def test_workflows_hub_skips_parents_without_workflows():
    from app.gateway.routers.workflows_hub import list_all_workflows

    store = MagicMock()
    no_workflow_parent = MagicMock()
    no_workflow_parent.value = {
        "thread_id": "px", "title": "regular chat",
        "created_at": "2026-04-29T09:00:00+00:00",
        "metadata": {},
    }
    store.asearch = AsyncMock(return_value=[no_workflow_parent])

    cp = MagicMock()
    cp.aget_tuple = AsyncMock(return_value=None)

    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = cp

    result = await list_all_workflows(req)
    assert result == {"parents": []}


@pytest.mark.asyncio
async def test_workflows_hub_classifies_failed_and_cancelled():
    """A child whose state contains _error is classified failed; if the
    error string starts with 'CancelledError', it's classified cancelled."""
    from app.gateway.routers.workflows_hub import list_all_workflows

    store = MagicMock()
    parent_record = {
        "thread_id": "p1", "title": "T",
        "created_at": "2026-04-29T10:00:00+00:00",
        "metadata": {"child_workflow_threads": [
            {"thread_id": "c-fail", "name": "demo-flow",
             "started_at": "2026-04-29T10:05:00+00:00"},
            {"thread_id": "c-cancel", "name": "demo-flow",
             "started_at": "2026-04-29T10:06:00+00:00"},
        ]},
    }
    item = MagicMock(); item.value = parent_record; item.key = "p1"
    store.asearch = AsyncMock(return_value=[item])

    def make_tuple(values):
        t = MagicMock(); t.checkpoint = {"channel_values": values}; return t

    async def aget_tuple(config):
        cid = config["configurable"]["thread_id"]
        if cid == "c-fail":
            return make_tuple({"is_done": True, "_error": "RuntimeError: boom"})
        if cid == "c-cancel":
            return make_tuple({
                "is_done": True,
                "_error": "CancelledError: workflow cancelled by user",
            })
        return None
    cp = MagicMock(); cp.aget_tuple = AsyncMock(side_effect=aget_tuple)

    req = MagicMock(); req.app.state.store = store; req.app.state.checkpointer = cp

    import deerflow.workflows.tools as wftools
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class _IS(BaseModel): pass
    spec = WorkflowSpec(
        name="demo-flow", description="x", factory=lambda **k: None,
        input_schema=_IS, done_field="is_done", report_field="report_markdown",
        progress_fields=[],
    )
    wftools._REGISTRY = WorkflowRegistry([spec], [])
    wftools._THREAD_TO_WORKFLOW = {
        "c-fail": "demo-flow", "c-cancel": "demo-flow",
    }

    result = await list_all_workflows(req)
    by_id = {w["child_thread_id"]: w
             for w in result["parents"][0]["workflows"]}
    assert by_id["c-fail"]["status"] == "failed"
    assert "RuntimeError" in by_id["c-fail"]["error"]
    assert by_id["c-cancel"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_workflows_hub_route_registered():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.routers.workflows_hub import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    # Without proper deps the endpoint will 500/503 — we only check it exists.
    r = client.get("/api/workflows/all")
    assert r.status_code in (200, 500, 503), r.status_code
