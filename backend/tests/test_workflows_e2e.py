"""End-to-end: lead_agent → start_workflow → demo_flow runs → emits to parent."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_full_lifecycle_demo_flow(monkeypatch):
    """Start, poll progress, complete, verify parent emit."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.tools import (
        get_workflow_progress,
        start_workflow,
    )

    saver = InMemorySaver()
    set_default_checkpointer(saver)

    _real_sleep = asyncio.sleep

    async def _noop(_s):
        await _real_sleep(0)

    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.7)

    reg = WorkflowRegistry(specs=[WorkflowSpec(
        name="demo-flow",
        description="d",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
        progress_fields=["current_round", "max_rounds", "history"],
    )], failures=[])
    monkeypatch.setattr(tools_mod, "_get_registry", lambda: reg)

    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "e2e-parent"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="run a workflow")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        # 1. Start workflow
        sr = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "yolo", "max_rounds": 3},
                },
                "id": "e2e-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )
        msg = sr.update["messages"][0].content
        child_tid = msg.split("thread_id=")[1].split(".")[0].strip()

        # 2. Poll progress until report_markdown appears in payload
        for i in range(50):
            await _real_sleep(0.05)
            pr = await get_workflow_progress.ainvoke(
                {
                    "name": "get_workflow_progress",
                    "args": {"thread_id": child_tid},
                    "id": f"e2e-poll-{i}",
                    "type": "tool_call",
                }
            )
            if "report_markdown" in pr.update["messages"][0].content:
                break
        else:
            pytest.fail("workflow never completed within 2.5s")

        # 3. Verify parent thread received the report system message
        parent_state = await parent_graph.aget_state(
            {"configurable": {"thread_id": parent_tid}}
        )
        msgs = [m.content for m in parent_state.values["messages"]]
        assert any(
            "[workflow:demo-flow] done" in m and "yolo" in m for m in msgs
        )

        # 4. Verify the final progress payload includes platform fields
        payload = pr.update["messages"][0].content
        assert "is_done" in payload
        assert "current_round" in payload
        assert "history" in payload
        assert "report_markdown" in payload

        # 5. Verify _hints is empty (no injection happened)
        assert '"_hints": []' in payload
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_full_lifecycle_with_hint_injection(monkeypatch):
    """Start workflow, inject a hint, verify _hints is in the progress payload."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.tools import (
        get_workflow_progress,
        inject_hint,
        start_workflow,
    )

    saver = InMemorySaver()
    set_default_checkpointer(saver)

    _real_sleep = asyncio.sleep

    async def _noop(_s):
        await _real_sleep(0)

    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.5)

    reg = WorkflowRegistry(specs=[WorkflowSpec(
        name="demo-flow",
        description="d",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
        progress_fields=["current_round", "history"],
    )], failures=[])
    monkeypatch.setattr(tools_mod, "_get_registry", lambda: reg)

    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "e2e-hint-parent"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="run with hint")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        sr = await start_workflow.ainvoke(
            {
                "name": "start_workflow",
                "args": {
                    "name": "demo-flow",
                    "params": {"task_name": "x", "max_rounds": 3},
                },
                "id": "eh-1",
                "type": "tool_call",
            },
            config={"configurable": {"thread_id": parent_tid}},
        )
        msg = sr.update["messages"][0].content
        child_tid = msg.split("thread_id=")[1].split(".")[0].strip()

        # Wait for the bg task to complete (it runs fast with _noop sleep)
        if child_tid in tools_mod._BG_TASKS:
            try:
                await tools_mod._BG_TASKS[child_tid]
            except Exception:
                pass

        # After completion, inject_hint still works (it just appends to a now-final state)
        await inject_hint.ainvoke(
            {
                "name": "inject_hint",
                "args": {"thread_id": child_tid, "hint": "post-mortem note"},
                "id": "eh-2",
                "type": "tool_call",
            }
        )

        pr = await get_workflow_progress.ainvoke(
            {
                "name": "get_workflow_progress",
                "args": {"thread_id": child_tid},
                "id": "eh-3",
                "type": "tool_call",
            }
        )
        payload = pr.update["messages"][0].content
        assert "post-mortem note" in payload
    finally:
        reset_default_checkpointer()
