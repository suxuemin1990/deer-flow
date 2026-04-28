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


def test_work_loop_increments_when_below_max():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = work_loop_node({"task_name": "x", "max_rounds": 3, "current_round": 0})
    assert out == {"current_round": 1, "is_done": False}


def test_work_loop_signals_done_at_max():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = work_loop_node({"task_name": "x", "max_rounds": 3, "current_round": 3})
    assert out == {"is_done": True}


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
