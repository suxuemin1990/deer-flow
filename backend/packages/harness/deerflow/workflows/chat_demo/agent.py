"""ChatDemo graph topology — same shape as demo_flow."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from deerflow.workflows.chat_demo.nodes.final_node import final_node
from deerflow.workflows.chat_demo.nodes.init_node import init_node
from deerflow.workflows.chat_demo.nodes.poll_wait_node import poll_wait_node
from deerflow.workflows.chat_demo.nodes.work_loop_node import work_loop_node
from deerflow.workflows.chat_demo.state import ChatDemoState


def _route_after_work_loop(state) -> Literal["poll_wait", "final"]:
    return "final" if state.get("is_done") else "poll_wait"


def make_graph(checkpointer=None):
    graph = StateGraph(ChatDemoState)
    graph.add_node("init", init_node)
    graph.add_node("work_loop", work_loop_node)
    graph.add_node("poll_wait", poll_wait_node)
    graph.add_node("final", final_node)
    graph.add_edge(START, "init")
    graph.add_edge("init", "work_loop")
    graph.add_conditional_edges(
        "work_loop",
        _route_after_work_loop,
        {"poll_wait": "poll_wait", "final": "final"},
    )
    graph.add_edge("poll_wait", "work_loop")
    graph.add_edge("final", END)
    return graph.compile(checkpointer=checkpointer)
