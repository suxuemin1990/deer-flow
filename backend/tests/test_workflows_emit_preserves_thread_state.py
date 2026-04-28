"""Regression test for emit_to_parent_thread schema pollution.

Bug: emit was using a generic MessagesState graph to call aupdate_state on a
parent thread whose actual schema is ThreadState. Sqlite-backed checkpointers
persist exactly the channel set the calling graph knows about, so after emit
the parent checkpoint loses ThreadState-only channels (title, thread_data,
artifacts).

Repro requires AsyncSqliteSaver — InMemorySaver carries unknown channels
through unchanged and hides the bug.

Fix: compile the noop graph against ThreadState so emit's writes land in a
checkpoint that still includes every ThreadState channel.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_emit_preserves_thread_state_fields_with_sqlite_checkpointer():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import END, START, StateGraph

    from deerflow.agents.thread_state import ThreadState
    from deerflow.workflows.emit import emit_to_parent_thread

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "ckpt.db")

        async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
            g = StateGraph(ThreadState)
            g.add_node("noop", lambda s: s)
            g.add_edge(START, "noop")
            g.add_edge("noop", END)
            parent_graph = g.compile(checkpointer=saver)

            parent_tid = "parent-thread-state-1"
            cfg = {"configurable": {"thread_id": parent_tid}}

            await parent_graph.ainvoke(
                {
                    "messages": [HumanMessage(content="hi")],
                    "title": "my chat",
                    "thread_data": {"workspace_path": "/tmp/ws"},
                    "artifacts": ["/tmp/a.txt"],
                },
                config=cfg,
            )

            # Sanity: seed reached the checkpoint.
            seeded = await parent_graph.aget_state(cfg)
            assert seeded.values.get("title") == "my chat"
            assert seeded.values.get("thread_data") == {"workspace_path": "/tmp/ws"}
            assert seeded.values.get("artifacts") == ["/tmp/a.txt"]

            # Act.
            await emit_to_parent_thread(
                parent_tid,
                "[workflow:demo-flow] done",
                checkpointer=saver,
            )

            # Assert: read via aget_state (matches the gateway /state endpoint
            # consumption pattern after serialize_channel_values).
            after = await parent_graph.aget_state(cfg)
            values = after.values

            # Message landed.
            messages = values.get("messages") or []
            contents = [getattr(m, "content", None) for m in messages]
            assert "[workflow:demo-flow] done" in contents

            # ThreadState-only fields survived.
            assert values.get("title") == "my chat", (
                "title should not be wiped by emit"
            )
            assert values.get("thread_data") == {"workspace_path": "/tmp/ws"}, (
                "thread_data should not be wiped by emit"
            )
            assert values.get("artifacts") == ["/tmp/a.txt"], (
                "artifacts should not be wiped by emit"
            )

            # No foreign channels leaked from the emit graph.
            foreign = [k for k in values.keys() if k.startswith("branch:")]
            assert foreign == [], (
                f"emit graph leaked internal channels into parent state: {foreign}"
            )
