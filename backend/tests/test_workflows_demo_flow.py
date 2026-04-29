"""Tests for the demo_flow workflow (first registered example)."""

from __future__ import annotations

import pytest


async def _async_noop(_s):
    return None


def test_input_schema_required_and_default_fields():
    from deerflow.workflows.demo_flow import DemoFlowInput

    schema = DemoFlowInput.model_json_schema()
    props = schema["properties"]
    assert "task_name" in props
    assert "max_rounds" in props
    assert schema["required"] == ["task_name"]
    instance = DemoFlowInput(task_name="x")
    assert instance.max_rounds == 3


def test_make_graph_compiles():
    from deerflow.workflows.demo_flow import make_graph

    graph = make_graph()
    assert graph is not None


def test_topology_has_pipeline_nodes():
    from deerflow.workflows.demo_flow import make_graph

    g = make_graph().get_graph()
    names = {n.id for n in g.nodes.values()}
    for expected in ("init", "work_loop", "poll_wait", "final"):
        assert expected in names


def test_init_node_resets_round():
    from deerflow.workflows.demo_flow.nodes.init_node import init_node

    out = init_node({"task_name": "x", "max_rounds": 3, "current_round": 99})
    assert out["current_round"] == 0


@pytest.mark.asyncio
async def test_work_loop_increments_when_below_max():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = await work_loop_node(
        {"task_name": "x", "max_rounds": 3, "current_round": 0}, config={}
    )
    assert out == {"current_round": 1, "is_done": False}


@pytest.mark.asyncio
async def test_work_loop_signals_done_at_max():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = await work_loop_node(
        {"task_name": "x", "max_rounds": 3, "current_round": 3}, config={}
    )
    assert out == {"is_done": True}


@pytest.mark.asyncio
async def test_work_loop_consumes_new_human_messages_into_history():
    """New HumanMessages on state['messages'] surface in the next round's history."""
    from langchain_core.messages import HumanMessage

    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = await work_loop_node(
        {
            "task_name": "x",
            "max_rounds": 3,
            "current_round": 0,
            "messages": [
                HumanMessage(content="go faster", id="m1"),
                HumanMessage(content="skip step 3", id="m2"),
            ],
        },
        config={"configurable": {"thread_id": "child-tid-1"}},
    )

    assert out["current_round"] == 1
    assert out["history"] == [
        {"round": 1, "hints": ["go faster", "skip step 3"]}
    ]
    assert out["_seen_msg_ids"] == {"m1", "m2"}


@pytest.mark.asyncio
async def test_work_loop_no_history_entry_when_no_hints():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = await work_loop_node(
        {"task_name": "x", "max_rounds": 3, "current_round": 0},
        config={"configurable": {"thread_id": "child-tid-empty"}},
    )
    assert "history" not in out


@pytest.mark.asyncio
async def test_poll_wait_appends_score(monkeypatch):
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as mod

    monkeypatch.setattr(mod.asyncio, "sleep", _async_noop)
    monkeypatch.setattr(mod.random, "uniform", lambda _a, _b: 0.55)

    out = await mod.poll_wait_node({"task_name": "x", "max_rounds": 3, "current_round": 1})
    assert out == {"history": [{"round": 1, "score": 0.55}]}


def test_final_renders_markdown_report():
    from deerflow.workflows.demo_flow.nodes.final_node import final_node

    out = final_node({
        "task_name": "yolo-task",
        "max_rounds": 2,
        "history": [{"round": 1, "score": 0.5}, {"round": 2, "score": 0.7}],
    })
    md = out["report_markdown"]
    assert "yolo-task" in md
    assert "| 1 | 0.5 |" in md
    assert "| 2 | 0.7 |" in md
    assert "0.7" in md


def test_final_tolerates_history_entries_without_score():
    """Hint entries injected by work_loop_node have no 'score' key."""
    from deerflow.workflows.demo_flow.nodes.final_node import final_node

    out = final_node({
        "task_name": "mixed",
        "max_rounds": 3,
        "history": [
            {"round": 1, "score": 0.5},
            {"round": 2, "hints": ["go faster"]},
            {"round": 2, "score": 0.7},
            {"round": 3, "score": 0.6},
        ],
    })
    md = out["report_markdown"]
    # Score rows still rendered.
    assert "| 1 | 0.5 |" in md
    assert "| 2 | 0.7 |" in md
    assert "| 3 | 0.6 |" in md
    # Best-round computed over score-bearing entries only.
    assert "Best round" in md
    assert "(score 0.7)" in md


@pytest.mark.parametrize("done,expected", [(True, "final"), (False, "poll_wait")])
def test_route_after_work_loop(done, expected):
    from deerflow.workflows.demo_flow.agent import _route_after_work_loop

    assert _route_after_work_loop({"is_done": done}) == expected


@pytest.mark.asyncio
async def test_full_pipeline_in_memory(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw

    monkeypatch.setattr(pw.asyncio, "sleep", _async_noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.6)

    graph = make_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}

    final_state = await graph.ainvoke({"task_name": "x", "max_rounds": 3}, config=cfg)

    assert final_state["current_round"] == 3
    assert len(final_state["history"]) == 3
    assert "x" in final_state["report_markdown"]
