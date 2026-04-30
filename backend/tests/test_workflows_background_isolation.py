"""Regression test: child workflow run must not inherit parent Pregel's
``__pregel_stream`` / runtime via ``var_child_runnable_config``.

When ``start_workflow`` fires from inside a lead-agent tool call,
``asyncio.create_task`` snapshots the parent task's contextvars. LangChain's
``var_child_runnable_config`` carries the parent Pregel's ``__pregel_stream``
and ``__pregel_runtime``; without scrubbing, ``ensure_config`` merges those
back into the child graph's effective config, and LangGraph wraps the child
loop's stream in a ``DuplexStream`` that forwards every child event into the
*parent* SSE — the user briefly sees child-workflow AIMessages render in the
parent chat before the lead agent's reply lands.

This test pins the contract: ``run_workflow_background`` MUST clear
``var_child_runnable_config`` before invoking the child graph.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_run_workflow_background_clears_inherited_runnable_config():
    from langchain_core.runnables.config import var_child_runnable_config

    from deerflow.workflows.background import run_workflow_background
    from deerflow.workflows.registry import WorkflowSpec

    # Simulate being inside a parent Pregel step: contextvar carries the
    # parent's stream / runtime keys.
    parent_marker = {
        "configurable": {
            "thread_id": "parent-tid",
            "__pregel_stream": object(),
            "__pregel_runtime": object(),
        }
    }
    var_child_runnable_config.set(parent_marker)

    captured: dict = {}

    class StubGraph:
        async def ainvoke(self, initial, config=None):
            captured["cv_at_ainvoke"] = var_child_runnable_config.get()
            captured["explicit_config"] = config
            return {}

        async def aget_state(self, cfg):
            return SimpleNamespace(values={})

        async def aupdate_state(self, *, config, values):
            return None

    def factory(*, checkpointer):
        return StubGraph()

    class _DummyInput:
        @classmethod
        def model_validate(cls, x):
            return cls()

        def model_dump(self):
            return {}

    spec = WorkflowSpec(
        name="iso-test",
        description="d",
        factory=factory,
        input_schema=_DummyInput,
        done_field="is_done",
        report_field="report_markdown",
    )

    await run_workflow_background(
        spec=spec,
        params={},
        child_thread_id="child-tid",
        parent_thread_id="parent-tid",
        checkpointer=None,  # type: ignore[arg-type]
    )

    cv = captured["cv_at_ainvoke"]
    # Either the contextvar is None entirely, or its configurable carries no
    # parent Pregel keys. Both satisfy "child run does not inherit parent
    # stream".
    if cv is not None:
        cfg = cv.get("configurable") or {}
        assert "__pregel_stream" not in cfg, (
            "child workflow inherited parent Pregel stream via "
            "var_child_runnable_config; child events will leak into parent SSE"
        )
        assert "__pregel_runtime" not in cfg, (
            "child workflow inherited parent Pregel runtime via "
            "var_child_runnable_config; child events will leak into parent SSE"
        )
