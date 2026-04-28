"""Tests for run_workflow_background success and failure paths."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_success_emits_report_to_parent_thread(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows.background import run_workflow_background
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowSpec

    async def _noop(_s):
        return None

    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.6)

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

    await run_workflow_background(
        spec=spec,
        params={"task_name": "x", "max_rounds": 2},
        child_thread_id="c1",
        parent_thread_id=parent_tid,
        checkpointer=saver,
    )

    parent_state = await parent_graph.aget_state(
        config={"configurable": {"thread_id": parent_tid}}
    )
    msgs = [m.content for m in parent_state.values["messages"]]
    assert any(
        "[workflow:demo-flow]" in m and "Exploration report" in m for m in msgs
    )


@pytest.mark.asyncio
async def test_failure_emits_error_and_writes_state(monkeypatch):
    from types import SimpleNamespace

    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows.background import run_workflow_background
    from deerflow.workflows.demo_flow import DemoFlowInput
    from deerflow.workflows.registry import WorkflowSpec

    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "p2"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    state_writes: list[dict] = []

    async def _bad_invoke(*_a, **_kw):
        raise RuntimeError("boom")

    async def _capture_update(*, config, values):  # noqa: ARG001
        state_writes.append(values)

    def _broken_factory(checkpointer=None):  # noqa: ARG001
        return SimpleNamespace(
            ainvoke=_bad_invoke,
            aupdate_state=_capture_update,
        )

    spec = WorkflowSpec(
        name="bad-wf",
        description="d",
        factory=_broken_factory,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
    )

    await run_workflow_background(
        spec=spec,
        params={"task_name": "x", "max_rounds": 1},
        child_thread_id="c-fail",
        parent_thread_id=parent_tid,
        checkpointer=saver,
    )

    # Parent should have a failure system message
    parent_state = await parent_graph.aget_state(
        config={"configurable": {"thread_id": parent_tid}}
    )
    msgs = [m.content for m in parent_state.values["messages"]]
    assert any("[workflow:bad-wf]" in m and "boom" in m for m in msgs)

    # Child state should have been updated with _error and is_done
    assert state_writes, "background runner did not call aupdate_state on failure"
    last_write = state_writes[-1]
    assert "_error" in last_write
    assert "boom" in last_write["_error"]
    assert last_write.get("is_done") is True


# ---------------------------------------------------------------------------
# Stamp tests (Phase 2 / Task A2): every terminal path of run_workflow_background
# must call stamp_parent_finish so the parent thread's store metadata gains a
# recent_workflow_finish_at ISO timestamp.
# ---------------------------------------------------------------------------


def _spec_with_factory(factory, name="stamp-wf"):
    from deerflow.workflows.demo_flow import DemoFlowInput
    from deerflow.workflows.registry import WorkflowSpec

    return WorkflowSpec(
        name=name,
        description="d",
        factory=factory,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
    )


@pytest.mark.asyncio
async def test_run_workflow_background_stamps_finish_on_success(monkeypatch):
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    import deerflow.runtime.store_singleton as ss
    from app.gateway.routers.threads import _store_upsert
    from deerflow.workflows.background import run_workflow_background

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)
    parent_tid = "p-stamp-success"
    await _store_upsert(store, parent_tid, metadata={})

    async def _ok_invoke(*_a, **_kw):
        return None

    async def _ok_update(*, config, values):  # noqa: ARG001
        return None

    async def _aget_state(_cfg):
        return SimpleNamespace(values={"report_markdown": "all done"})

    def _factory(checkpointer=None):  # noqa: ARG001
        return SimpleNamespace(
            ainvoke=_ok_invoke,
            aupdate_state=_ok_update,
            aget_state=_aget_state,
        )

    await run_workflow_background(
        spec=_spec_with_factory(_factory, name="ok-wf"),
        params={"task_name": "x", "max_rounds": 1},
        child_thread_id="c-ok",
        parent_thread_id=parent_tid,
        checkpointer=InMemorySaver(),
    )

    rec = await store.aget(("threads",), parent_tid)
    assert rec is not None
    assert "recent_workflow_finish_at" in rec.value["metadata"]


@pytest.mark.asyncio
async def test_run_workflow_background_stamps_finish_on_failure(monkeypatch):
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    import deerflow.runtime.store_singleton as ss
    from app.gateway.routers.threads import _store_upsert
    from deerflow.workflows.background import run_workflow_background

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)
    parent_tid = "p-stamp-fail"
    await _store_upsert(store, parent_tid, metadata={})

    async def _bad_invoke(*_a, **_kw):
        raise RuntimeError("boom")

    async def _ok_update(*, config, values):  # noqa: ARG001
        return None

    def _factory(checkpointer=None):  # noqa: ARG001
        return SimpleNamespace(
            ainvoke=_bad_invoke,
            aupdate_state=_ok_update,
        )

    await run_workflow_background(
        spec=_spec_with_factory(_factory, name="fail-wf"),
        params={"task_name": "x", "max_rounds": 1},
        child_thread_id="c-fail-stamp",
        parent_thread_id=parent_tid,
        checkpointer=InMemorySaver(),
    )

    rec = await store.aget(("threads",), parent_tid)
    assert rec is not None
    assert "recent_workflow_finish_at" in rec.value["metadata"]


@pytest.mark.asyncio
async def test_run_workflow_background_stamps_finish_on_cancel(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    import deerflow.runtime.store_singleton as ss
    from app.gateway.routers.threads import _store_upsert
    from deerflow.workflows.background import run_workflow_background

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)
    parent_tid = "p-stamp-cancel"
    await _store_upsert(store, parent_tid, metadata={})

    async def _hang_invoke(*_a, **_kw):
        await asyncio.sleep(60)

    async def _ok_update(*, config, values):  # noqa: ARG001
        return None

    def _factory(checkpointer=None):  # noqa: ARG001
        return SimpleNamespace(
            ainvoke=_hang_invoke,
            aupdate_state=_ok_update,
        )

    task = asyncio.create_task(
        run_workflow_background(
            spec=_spec_with_factory(_factory, name="cancel-wf"),
            params={"task_name": "x", "max_rounds": 1},
            child_thread_id="c-cancel-stamp",
            parent_thread_id=parent_tid,
            checkpointer=InMemorySaver(),
        )
    )
    # Yield once so the task starts running and enters ainvoke's sleep.
    await asyncio.sleep(0)
    task.cancel()
    await task  # run_workflow_background swallows CancelledError internally

    rec = await store.aget(("threads",), parent_tid)
    assert rec is not None
    assert "recent_workflow_finish_at" in rec.value["metadata"]
