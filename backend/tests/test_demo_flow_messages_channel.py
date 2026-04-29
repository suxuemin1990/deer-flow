"""Demo flow consumes new HumanMessages through state['messages']."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_demo_flow_records_injected_human_message_in_history():
    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    graph = make_graph(checkpointer=cp)
    child_tid = "child-demo"
    config = {"configurable": {"thread_id": child_tid}}

    # Inject a user message before running
    await inject_user_message_to_workflow(
        child_tid, "use dropout", checkpointer=cp,
    )

    # Run demo flow
    final = await graph.ainvoke(
        {"task_name": "t", "max_rounds": 1, "_parent_thread_id": "p"},
        config=config,
    )

    history = final.get("history") or []
    # The hint must be reflected somewhere in history (work_loop_node should
    # have observed the new HumanMessage and stamped it into history).
    hint_entries = [e for e in history if "hints" in e]
    assert hint_entries, f"expected at least one hint entry, got history={history!r}"
    seen_flat = [h for e in hint_entries for h in (e.get("hints") or [])]
    assert any("dropout" in (h or "") for h in seen_flat), (
        f"expected 'dropout' to appear in recorded hints; got {seen_flat!r}"
    )


@pytest.mark.asyncio
async def test_demo_flow_seen_msg_ids_prevents_double_processing():
    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    graph = make_graph(checkpointer=cp)
    child_tid = "child-demo-2"
    config = {"configurable": {"thread_id": child_tid}}

    await inject_user_message_to_workflow(
        child_tid, "first hint", checkpointer=cp,
    )

    final = await graph.ainvoke(
        {"task_name": "t", "max_rounds": 2, "_parent_thread_id": "p"},
        config=config,
    )

    history = final.get("history") or []
    hint_entries = [e for e in history if "hints" in e]
    # The hint should be recorded exactly once across both rounds (not
    # re-processed on the second round).
    flat = [h for e in hint_entries for h in (e.get("hints") or [])]
    assert flat.count("first hint") == 1, (
        f"hint should be processed exactly once across rounds; got {flat!r}"
    )
