"""Tests for parent-thread idle gating in run_workflow_background.

Goal: bg task must wait for parent's RunManager to report no inflight runs
before calling emit_to_parent_thread, otherwise the emit forks the parent's
checkpoint chain (the still-streaming lead_agent overwrites the emit).

Behavior covered here:
  1. With a registered RunManager that says inflight, emit is delayed until
     RunManager reports idle.
  2. With a registered RunManager that says idle from the start, no delay.
  3. With NO registered RunManager (e.g. langgraph dev mode, unit tests),
     emit fires immediately — degrade gracefully, never block.
  4. Wait honours a timeout: if parent never goes idle, emit fires anyway
     (the parent thread might be stuck; we still want the report on disk).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Lightweight RunManager stand-in.
# ---------------------------------------------------------------------------


def _make_fake_run_manager(*, inflight_sequence):
    """Build a stand-in whose ``has_inflight`` returns each value in turn,
    repeating the last value indefinitely."""
    seq = list(inflight_sequence)
    mgr = MagicMock(name="FakeRunManager")

    async def _has_inflight(_tid):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    mgr.has_inflight = _has_inflight
    return mgr


@pytest.mark.asyncio
async def test_emit_waits_until_parent_thread_is_idle(monkeypatch):
    from deerflow.runtime.run_manager_singleton import (
        reset_default_run_manager,
        set_default_run_manager,
    )
    from deerflow.workflows import background as bg

    reset_default_run_manager()
    fake = _make_fake_run_manager(inflight_sequence=[True, True, False])
    set_default_run_manager(fake)

    sleeps: list[float] = []

    async def _track_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(bg.asyncio, "sleep", _track_sleep)

    emit_calls: list[tuple[str, str]] = []

    async def _fake_emit(parent_tid, content, *, checkpointer):
        emit_calls.append((parent_tid, content))

    monkeypatch.setattr(bg, "emit_to_parent_thread", _fake_emit)

    await bg._wait_for_parent_idle("p1", timeout_s=5.0, poll_interval_s=0.1)

    assert sleeps, "should have slept while parent was inflight"
    # has_inflight returned True, True, False — so we sleep at least twice.
    assert len(sleeps) >= 2

    reset_default_run_manager()


@pytest.mark.asyncio
async def test_emit_no_wait_when_parent_already_idle(monkeypatch):
    from deerflow.runtime.run_manager_singleton import (
        reset_default_run_manager,
        set_default_run_manager,
    )
    from deerflow.workflows import background as bg

    reset_default_run_manager()
    fake = _make_fake_run_manager(inflight_sequence=[False])
    set_default_run_manager(fake)

    sleeps: list[float] = []

    async def _track_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(bg.asyncio, "sleep", _track_sleep)

    await bg._wait_for_parent_idle("p1", timeout_s=5.0, poll_interval_s=0.1)

    assert sleeps == [], "should not have slept when parent was idle"

    reset_default_run_manager()


@pytest.mark.asyncio
async def test_wait_is_noop_when_no_run_manager_registered(monkeypatch):
    from deerflow.runtime.run_manager_singleton import reset_default_run_manager
    from deerflow.workflows import background as bg

    reset_default_run_manager()

    sleeps: list[float] = []

    async def _track_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(bg.asyncio, "sleep", _track_sleep)

    # Should return immediately without raising.
    await bg._wait_for_parent_idle("p1", timeout_s=5.0, poll_interval_s=0.1)

    assert sleeps == []


@pytest.mark.asyncio
async def test_wait_honours_timeout(monkeypatch):
    """If parent never goes idle, give up after timeout_s and let caller emit."""
    from deerflow.runtime.run_manager_singleton import (
        reset_default_run_manager,
        set_default_run_manager,
    )
    from deerflow.workflows import background as bg

    reset_default_run_manager()
    fake = _make_fake_run_manager(inflight_sequence=[True])  # always inflight
    set_default_run_manager(fake)

    sleeps: list[float] = []
    fake_now = [0.0]

    async def _fake_sleep(d):
        sleeps.append(d)
        fake_now[0] += d

    monkeypatch.setattr(bg.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(bg.time, "monotonic", lambda: fake_now[0])

    await bg._wait_for_parent_idle("p1", timeout_s=1.0, poll_interval_s=0.2)

    # Should have stopped polling after ~1s of fake elapsed time.
    assert sum(sleeps) >= 1.0
    assert sum(sleeps) < 2.0  # didn't loop way past timeout

    reset_default_run_manager()


@pytest.mark.asyncio
async def test_run_workflow_background_calls_wait_before_emit(monkeypatch):
    """End-to-end: success path invokes _wait_for_parent_idle, then emits."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows import background as bg
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowSpec

    async def _noop(_s):
        return None

    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.6)

    order: list[str] = []
    wait_called = AsyncMock()

    async def _wait(parent_tid, **kw):
        order.append(f"wait:{parent_tid}")
        await wait_called(parent_tid, **kw)

    async def _fake_emit(parent_tid, content, *, checkpointer):
        order.append(f"emit:{parent_tid}")

    monkeypatch.setattr(bg, "_wait_for_parent_idle", _wait)
    monkeypatch.setattr(bg, "emit_to_parent_thread", _fake_emit)

    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "p1"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    spec = WorkflowSpec(
        name="demo-flow",
        description="d",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
    )

    await bg.run_workflow_background(
        spec=spec,
        params={"task_name": "x", "max_rounds": 2},
        child_thread_id="c1",
        parent_thread_id=parent_tid,
        checkpointer=saver,
    )

    assert order == [f"wait:{parent_tid}", f"emit:{parent_tid}"]
    wait_called.assert_awaited_once()
