"""Tests for POST /api/threads/{tid}/workflows/{cid}/cancel."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_cancel_endpoint_cancels_known_child(monkeypatch):
    import deerflow.workflows.tools as wftools
    from app.gateway.routers.threads import cancel_active_workflow

    parent_tid = "p"
    child_tid = "c"

    async def _runner():
        await asyncio.sleep(60)

    task = asyncio.create_task(_runner())
    monkeypatch.setattr(wftools, "_BG_TASKS", {child_tid: task}, raising=False)
    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {child_tid: "demo-flow"}, raising=False)

    req = MagicMock()
    result = await cancel_active_workflow(parent_tid, child_tid, request=req)

    assert result == {"ok": True}
    # Yield once so the cancellation propagates.
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_endpoint_unknown_child(monkeypatch):
    import deerflow.workflows.tools as wftools
    from app.gateway.routers.threads import cancel_active_workflow

    monkeypatch.setattr(wftools, "_BG_TASKS", {}, raising=False)
    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {}, raising=False)

    req = MagicMock()
    result = await cancel_active_workflow("p", "ghost", request=req)
    assert result == {"ok": False, "reason": "not a registered workflow thread"}


@pytest.mark.asyncio
async def test_cancel_endpoint_already_done(monkeypatch):
    import deerflow.workflows.tools as wftools
    from app.gateway.routers.threads import cancel_active_workflow

    async def _done():
        return None
    task = asyncio.create_task(_done())
    await task

    monkeypatch.setattr(wftools, "_BG_TASKS", {"c": task}, raising=False)
    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {"c": "demo-flow"}, raising=False)

    req = MagicMock()
    result = await cancel_active_workflow("p", "c", request=req)
    assert result == {"ok": False, "reason": "workflow already finished"}
