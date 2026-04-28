"""Tests for GET /api/threads/{tid}/workflows/active."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


def _make_request(store, checkpointer):
    """Mimic FastAPI's Request for the helpers that read app.state."""
    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = checkpointer
    return req


async def _seed_child(checkpointer, child_tid: str, values: dict) -> None:
    """Write a single checkpoint with given channel_values for a child thread."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph

    class S(TypedDict, total=False):
        is_done: bool
        current_round: int
        max_rounds: int
        report: str

    g = StateGraph(S)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    graph = g.compile(checkpointer=checkpointer)
    await graph.aupdate_state(
        config={"configurable": {"thread_id": child_tid}},
        values=values,
    )


@pytest.mark.asyncio
async def test_active_endpoint_returns_only_running(monkeypatch):
    """Of two children, one done and one running, only the running one comes back."""
    from app.gateway.routers.threads import _store_upsert, list_active_workflows

    store = InMemoryStore()
    cp = InMemorySaver()
    parent = "parent-A"

    await _store_upsert(store, parent, metadata={
        "child_workflow_threads": [
            {"thread_id": "c-running", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
            {"thread_id": "c-done", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    await _seed_child(cp, "c-running", {"is_done": False, "current_round": 3, "max_rounds": 10})
    await _seed_child(cp, "c-done", {"is_done": True, "current_round": 10, "max_rounds": 10, "report": "ok"})

    # Fake registry so the endpoint can look up progress_fields.
    from pydantic import BaseModel

    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    class P(BaseModel): ...
    spec = WorkflowSpec(
        name="demo-flow", description="", factory=lambda **_: None,
        input_schema=P, done_field="is_done", report_field="report",
        progress_fields=["current_round", "max_rounds"],
    )
    fake_reg = WorkflowRegistry([spec], failures=[])
    import deerflow.workflows.tools as wftools
    monkeypatch.setattr(wftools, "_REGISTRY", fake_reg)

    req = _make_request(store, cp)
    result = await list_active_workflows(parent, request=req)

    assert len(result["active"]) == 1
    item = result["active"][0]
    assert item["thread_id"] == "c-running"
    assert item["name"] == "demo-flow"
    assert item["is_done"] is False
    assert item["progress"] == {"current_round": 3, "max_rounds": 10}


@pytest.mark.asyncio
async def test_active_endpoint_handles_unknown_workflow_name(monkeypatch):
    """Child whose workflow name isn't registered is skipped, doesn't crash."""
    import deerflow.workflows.tools as wftools
    from app.gateway.routers.threads import _store_upsert, list_active_workflows
    from deerflow.workflows.registry import WorkflowRegistry

    store = InMemoryStore()
    cp = InMemorySaver()
    await _store_upsert(store, "p", metadata={
        "child_workflow_threads": [
            {"thread_id": "c", "name": "ghost-workflow", "started_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    monkeypatch.setattr(wftools, "_REGISTRY", WorkflowRegistry([], failures=[]))

    req = _make_request(store, cp)
    result = await list_active_workflows("p", request=req)
    assert result == {"active": []}


@pytest.mark.asyncio
async def test_active_endpoint_no_metadata_returns_empty(monkeypatch):
    from app.gateway.routers.threads import list_active_workflows

    req = _make_request(InMemoryStore(), InMemorySaver())
    result = await list_active_workflows("missing", request=req)
    assert result == {"active": []}
