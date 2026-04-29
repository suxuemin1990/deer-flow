"""Tests for the 4 LLM-facing workflow tools."""

from __future__ import annotations

import asyncio
import re

import pytest


def _setup_registry_and_checkpointer(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.runtime.checkpointer_singleton import set_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    saver = InMemorySaver()
    set_default_checkpointer(saver)

    _real_sleep = asyncio.sleep

    async def _noop(_s):
        # yield control once instead of the real 2s wait, so background
        # tasks (and the test polling loop) keep making progress
        await _real_sleep(0)

    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.5)

    registry = WorkflowRegistry(
        specs=[WorkflowSpec(
            name="demo-flow",
            description="d",
            factory=make_graph,
            input_schema=DemoFlowInput,
            done_field="is_done",
            report_field="report_markdown",
            progress_fields=["current_round", "max_rounds", "history"],
        )],
        failures=[],
    )
    monkeypatch.setattr(tools_mod, "_get_registry", lambda: registry)
    return saver, registry


@pytest.mark.asyncio
async def test_start_workflow_returns_thread_id_and_runs_in_background(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)

    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "chat-1"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="start it")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 2},
                },
                "id": "tc-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )

        msg = result.update["messages"][0].content
        assert "demo-flow" in msg
        assert "thread_id=" in msg

        # Wait for the bg task to complete by introspecting tools._BG_TASKS.
        import re

        from deerflow.workflows import tools as tools_mod
        # Extract child thread id from the tool message.
        match = re.search(r"thread_id=([0-9a-f-]+)", msg)
        assert match
        child_tid = match.group(1)
        bg_task = tools_mod._BG_TASKS.get(child_tid)
        if bg_task is not None:
            await bg_task

        parent_state = await parent_graph.aget_state(
            {"configurable": {"thread_id": parent_tid}}
        )
        messages = parent_state.values["messages"]
        if not any("[workflow:demo-flow] done" in m.content for m in messages):
            pytest.fail("background workflow never emitted to parent thread")
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_start_workflow_unknown_name_returns_tool_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import start_workflow

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {"name": "nope", "params": {}},
                "id": "tc-x",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": "chat-2"}},
        )
        msg = result.update["messages"][0].content
        assert "nope" in msg
        assert "not registered" in msg.lower() or "unknown" in msg.lower()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_start_workflow_invalid_params_returns_tool_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import start_workflow

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {"name": "demo-flow", "params": {}},  # missing task_name
                "id": "tc-y",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": "chat-3"}},
        )
        msg = result.update["messages"][0].content
        assert "task_name" in msg
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_inject_hint_writes_to_inbox(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.tools import inject_hint, start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)
    parent_tid = "chat-h1"

    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        # Start a workflow with enough rounds to leave it running while we inject.
        start_result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 20},
                },
                "id": "h-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )
        msg = start_result.update["messages"][0].content
        # Extract child_thread_id from the success message
        child_tid = re.search(r"thread_id=([0-9a-f-]+)", msg).group(1)

        result = await inject_hint.ainvoke(
            {
                "name": "inject_hint",
                "args": {"thread_id": child_tid, "hint": "try smaller lr"},
                "id": "h-2",
                "type": "tool_call",
            }
        )
        assert "inject" in result.update["messages"][0].content.lower()

        # Hint lands as a HumanMessage in the child workflow's messages
        # channel — verify via the same checkpointer.
        from deerflow.workflows.demo_flow import make_graph
        graph = make_graph(checkpointer=saver)
        st = await graph.aget_state({"configurable": {"thread_id": child_tid}})
        msgs = st.values.get("messages") or []
        from langchain_core.messages import HumanMessage as _HM
        assert any(
            isinstance(m, _HM) and "try smaller lr" in m.content for m in msgs
        ), f"expected HumanMessage with hint in child state; got {msgs!r}"

        # Cancel the running task so the test exits cleanly
        if child_tid in tools_mod._BG_TASKS:
            tools_mod._BG_TASKS[child_tid].cancel()
            try:
                await tools_mod._BG_TASKS[child_tid]
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_inject_hint_unknown_thread_returns_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import inject_hint

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await inject_hint.ainvoke(
            {
                "name": "inject_hint",
                "args": {"thread_id": "not-a-workflow-thread", "hint": "x"},
                "id": "h-3",
                "type": "tool_call",
            }
        )
        msg = result.update["messages"][0].content
        assert "not" in msg.lower() and "workflow" in msg.lower()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_cancel_workflow_cancels_task_and_writes_error(monkeypatch):
    """Cancel-mid-flight: real asyncio.sleep so we can interrupt a running node."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.tools import cancel_workflow, start_workflow

    # Custom setup: do NOT patch poll_wait's sleep — we need real sleep to cancel.
    saver = InMemorySaver()
    set_default_checkpointer(saver)
    registry = WorkflowRegistry(
        specs=[WorkflowSpec(
            name="demo-flow",
            description="d",
            factory=make_graph,
            input_schema=DemoFlowInput,
            done_field="is_done",
            report_field="report_markdown",
            progress_fields=["current_round"],
        )],
        failures=[],
    )
    monkeypatch.setattr(tools_mod, "_get_registry", lambda: registry)

    parent_tid = "chat-c1"
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        # max_rounds=20 (DemoFlowInput.le=20); ~40s real runtime — plenty for cancel
        start_result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 20},
                },
                "id": "c-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )
        msg = start_result.update["messages"][0].content
        child_tid = re.search(r"thread_id=([0-9a-f-]+)", msg).group(1)

        # Let the workflow enter a poll_wait sleep before cancelling.
        await asyncio.sleep(0.3)

        cancel_result = await cancel_workflow.ainvoke(
            {
                "name": "cancel_workflow",
                "args": {"thread_id": child_tid},
                "id": "c-2",
                "type": "tool_call",
            }
        )
        assert "cancel" in cancel_result.update["messages"][0].content.lower()

        # Wait for the task to settle (background runner's CancelledError branch finishes)
        if child_tid in tools_mod._BG_TASKS:
            try:
                await tools_mod._BG_TASKS[child_tid]
            except (asyncio.CancelledError, Exception):
                pass
        else:
            # done_callback already removed it — give the lifecycle a tick
            await asyncio.sleep(0.1)

        graph = make_graph(checkpointer=saver)
        state = await graph.aget_state({"configurable": {"thread_id": child_tid}})
        assert state.values.get("_error")
        assert "cancel" in state.values["_error"].lower()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_cancel_workflow_unknown_thread_returns_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import cancel_workflow

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await cancel_workflow.ainvoke(
            {
                "name": "cancel_workflow",
                "args": {"thread_id": "unknown"},
                "id": "c-x",
                "type": "tool_call",
            }
        )
        assert "not" in result.update["messages"][0].content.lower()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_cancel_workflow_already_finished_returns_error(monkeypatch):
    """If the workflow already completed, cancel should report 'no longer running'."""
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.tools import cancel_workflow

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        # Manually register a fake "finished workflow" entry without a live task.
        tools_mod._THREAD_TO_WORKFLOW["finished-tid"] = "demo-flow"
        result = await cancel_workflow.ainvoke(
            {
                "name": "cancel_workflow",
                "args": {"thread_id": "finished-tid"},
                "id": "c-z",
                "type": "tool_call",
            }
        )
        msg = result.update["messages"][0].content.lower()
        assert "no longer running" in msg or "running" in msg
    finally:
        tools_mod._THREAD_TO_WORKFLOW.pop("finished-tid", None)
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_get_workflow_progress_returns_platform_and_progress_fields(monkeypatch):
    """After completion the payload includes platform fields, progress_fields, and report."""
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.tools import get_workflow_progress, start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)
    parent_tid = "chat-p1"

    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        start_result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 2},
                },
                "id": "p-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )
        msg = start_result.update["messages"][0].content
        child_tid = re.search(r"thread_id=([0-9a-f-]+)", msg).group(1)

        # Wait for the bg task to finish
        if child_tid in tools_mod._BG_TASKS:
            try:
                await tools_mod._BG_TASKS[child_tid]
            except Exception:
                pass

        progress_result = await get_workflow_progress.ainvoke(
            {
                "name": "get_workflow_progress",
                "args": {"thread_id": child_tid},
                "id": "p-2",
                "type": "tool_call",
            }
        )
        content = progress_result.update["messages"][0].content
        # Payload is JSON; inspect by string match to keep the assertion robust
        # to formatting tweaks
        assert "is_done" in content
        assert "current_round" in content
        assert "history" in content
        assert "report_markdown" in content
        assert "demo-flow" in content
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_get_workflow_progress_unknown_thread_returns_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import get_workflow_progress

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await get_workflow_progress.ainvoke(
            {
                "name": "get_workflow_progress",
                "args": {"thread_id": "unknown-tid"},
                "id": "p-x",
                "type": "tool_call",
            }
        )
        assert "not" in result.update["messages"][0].content.lower()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_start_workflow_appends_child_to_parent_metadata(monkeypatch):
    """When a parent thread record exists, start_workflow appends to its child list."""
    from langgraph.store.memory import InMemoryStore

    from app.gateway.routers.threads import _store_upsert
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.runtime.store_singleton import (
        reset_default_store,
        set_default_store,
    )
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.tools import start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)
    parent_tid = "chat-store-1"

    store = InMemoryStore()
    set_default_store(store)
    await _store_upsert(store, parent_tid)  # parent record exists

    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 2},
                },
                "id": "store-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )
        msg = result.update["messages"][0].content
        child_tid = re.search(r"thread_id=([0-9a-f-]+)", msg).group(1)

        # Wait for bg task to complete (uses _noop sleep so it's fast)
        if child_tid in tools_mod._BG_TASKS:
            try:
                await tools_mod._BG_TASKS[child_tid]
            except Exception:
                pass

        rec = await store.aget(("threads",), parent_tid)
        assert rec is not None
        children = (rec.value.get("metadata") or {}).get("child_workflow_threads") or []
        assert any(c["thread_id"] == child_tid and c["name"] == "demo-flow" for c in children)
    finally:
        reset_default_store()
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_inject_hint_writes_human_message_via_messages_channel(monkeypatch):
    """inject_hint must call inject_user_message_to_workflow, not push_hint,
    and must pass the looked-up WorkflowSpec so the appender uses the
    workflow's own state schema (not ThreadState)."""
    import deerflow.workflows.tools as wftools
    from deerflow.workflows.tools import inject_hint

    # Build a fake registry the tool can resolve "demo-flow" against.
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class _IS(BaseModel):
        pass

    fake_spec = WorkflowSpec(
        name="demo-flow", description="x", factory=lambda **k: object(),
        input_schema=_IS, done_field="is_done",
        report_field="report_markdown", progress_fields=[],
    )
    monkeypatch.setattr(
        wftools, "_THREAD_TO_WORKFLOW", {"c": "demo-flow"}, raising=False,
    )
    monkeypatch.setattr(
        wftools, "_REGISTRY", WorkflowRegistry([fake_spec], []), raising=False,
    )

    captured: dict = {}
    async def fake_inject(child_tid, content, *, spec, checkpointer):
        captured["child_tid"] = child_tid
        captured["content"] = content
        captured["spec_name"] = spec.name

    import deerflow.workflows.emit as emit_mod
    monkeypatch.setattr(emit_mod, "inject_user_message_to_workflow", fake_inject)
    monkeypatch.setattr(wftools, "get_default_checkpointer", lambda: object())

    result = await inject_hint.ainvoke({
        "name": "inject_hint",
        "args": {"thread_id": "c", "hint": "use dropout"},
        "id": "tc-1",
        "type": "tool_call",
    })

    assert captured == {
        "child_tid": "c",
        "content": "use dropout",
        "spec_name": "demo-flow",
    }
    msg = result.update["messages"][0]
    assert "demo-flow" in msg.content


@pytest.mark.asyncio
async def test_start_workflow_tool_message_carries_workflow_link_payload(monkeypatch):
    """The ToolMessage returned by start_workflow must carry an
    additional_kwargs.workflow_link payload so the frontend can render
    a clickable card."""
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.tools import start_workflow

    _setup_registry_and_checkpointer(monkeypatch)

    # Stub run_workflow_background so no real task starts
    async def fake_run(**kwargs):
        return None

    monkeypatch.setattr(tools_mod, "run_workflow_background", fake_run)

    # Stub _record_child_workflow_thread to a no-op
    async def fake_record(*a, **k):
        return None

    monkeypatch.setattr(tools_mod, "_record_child_workflow_thread", fake_record)

    try:
        result = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 2},
                },
                "id": "tc-link",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": "parent-link"}},
        )

        msg = result.update["messages"][0]
        payload = msg.additional_kwargs
        assert payload.get("element") == "workflow_link", (
            f"expected element='workflow_link' for frontend dispatch, got "
            f"additional_kwargs={payload!r}"
        )
        link = payload.get("workflow_link")
        assert isinstance(link, dict)
        assert link["name"] == "demo-flow"
        assert link["child_thread_id"]
        assert link["url"] == f"/workspace/workflows/{link['child_thread_id']}"

        # Text content must still mention the hub for non-rich-UI clients
        assert "工作流中心" in msg.content or "Workflow Hub" in msg.content
    finally:
        reset_default_checkpointer()
