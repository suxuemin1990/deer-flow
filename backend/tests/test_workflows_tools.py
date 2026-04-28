"""Tests for the 4 LLM-facing workflow tools."""

from __future__ import annotations

import asyncio

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
async def test_inject_hint_writes_to_state(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import make_graph
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
        child_tid = msg.split("thread_id=")[1].split(".")[0].strip()

        result = await inject_hint.ainvoke(
            {
                "name": "inject_hint",
                "args": {"thread_id": child_tid, "hint": "try smaller lr"},
                "id": "h-2",
                "type": "tool_call",
            }
        )
        assert "inject" in result.update["messages"][0].content.lower()

        # Verify _hints made it into the child state
        graph = make_graph(checkpointer=saver)
        state = await graph.aget_state({"configurable": {"thread_id": child_tid}})
        assert "try smaller lr" in (state.values.get("_hints") or [])

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
