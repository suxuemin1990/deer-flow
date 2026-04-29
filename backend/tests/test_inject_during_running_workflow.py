"""Bug 5 regression — injection during a running workflow must persist.

Before fix: aupdate_state from inject_user_message_to_workflow wrote a
sibling checkpoint; running pregel's next step overwrote it; messages
lost. After fix: POST routes to hints_inbox while running task drains it
and emits HumanMessages via node return.

Uses AsyncSqliteSaver to match production; InMemorySaver shares dicts
across reads/writes and would not reproduce the race.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_inject_during_running_workflow_persists_message(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows import emit as emit_mod
    from deerflow.workflows import hints_inbox as ib
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.tools import start_workflow

    db = tmp_path / "checkpoints.sqlite"
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        set_default_checkpointer(saver)
        ib.reset_for_test()

        registry = WorkflowRegistry(
            specs=[WorkflowSpec(
                name="demo-flow",
                description="d",
                factory=make_graph,
                input_schema=DemoFlowInput,
                done_field="is_done",
                report_field="report_markdown",
                progress_fields=["current_round", "max_rounds", "history"],
                accepts_chat=True,
            )],
            failures=[],
        )
        original = tools_mod._get_registry
        tools_mod._get_registry = lambda: registry  # noqa: SLF001
        try:
            # Seed parent thread (so start_workflow has somewhere to emit notices)
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, START, MessagesState, StateGraph

            g = StateGraph(MessagesState)
            g.add_node("noop", lambda s: s)
            g.add_edge(START, "noop")
            g.add_edge("noop", END)
            await g.compile(checkpointer=saver).ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config={"configurable": {"thread_id": "p-1"}},
            )

            # Start a slow workflow (max_rounds high enough to leave it
            # running while we inject; demo-flow's poll_wait sleeps 2s).
            result = await start_workflow.ainvoke(
                {
                    "name": "start_workflow",
                    "args": {
                        "name": "demo-flow",
                        "params": {"task_name": "x", "max_rounds": 5},
                    },
                    "id": "h-1",
                    "type": "tool_call",
                },
                config={"configurable": {"thread_id": "p-1"}},
            )
            import re
            child_tid = re.search(
                r"thread_id=([0-9a-f-]+)", result.update["messages"][0].content
            ).group(1)

            # Wait for the workflow to actually start ticking (at least 1 round).
            for _ in range(30):
                await asyncio.sleep(0.2)
                cp = await saver.aget_tuple(
                    {"configurable": {"thread_id": child_tid, "checkpoint_ns": ""}}
                )
                if cp and (cp.checkpoint or {}).get("channel_values", {}).get("current_round", 0) >= 1:
                    break

            # Inject while running.
            await emit_mod.inject_user_message_to_workflow(
                child_tid,
                "please refine — try smaller lr",
                spec=registry.get("demo-flow"),
                checkpointer=saver,
            )

            # Wait for workflow to complete (poll_wait * remaining rounds < 15s).
            task = tools_mod._BG_TASKS.get(child_tid)
            if task is not None:
                await asyncio.wait_for(asyncio.shield(task), timeout=20)

            # Verify HumanMessage with our content survives in final state.
            graph = make_graph(checkpointer=saver)
            final = await graph.aget_state(
                {"configurable": {"thread_id": child_tid}}
            )
            from langchain_core.messages import HumanMessage as _HM
            msgs = final.values.get("messages") or []
            assert any(
                isinstance(m, _HM) and "smaller lr" in m.content for m in msgs
            ), f"expected injected HumanMessage to persist; got {msgs!r}"
        finally:
            tools_mod._get_registry = original
            reset_default_checkpointer()
            ib.reset_for_test()
