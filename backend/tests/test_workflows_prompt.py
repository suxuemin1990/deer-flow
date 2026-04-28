"""Tests for the workflow catalog rendered into lead_agent's system prompt."""

from __future__ import annotations

from pydantic import BaseModel, Field


class _SampleInput(BaseModel):
    name: str = Field(description="Task name")
    rounds: int = Field(default=5, ge=1, description="Round budget")
    target: str = Field(default="mAP", description="Target metric")


def _factory(checkpointer=None):  # noqa: ARG001
    return None


def test_render_catalog_lists_each_workflow():
    from deerflow.workflows.prompt import render_workflow_catalog
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    reg = WorkflowRegistry(specs=[
        WorkflowSpec(
            name="demo-flow",
            description="A demo workflow.",
            factory=_factory,
            input_schema=_SampleInput,
            done_field="is_done",
            report_field="report_markdown",
            hint_behavior_doc="Hints are stored but not consumed.",
        ),
    ], failures=[])

    out = render_workflow_catalog(reg)
    assert "demo-flow" in out
    assert "A demo workflow." in out
    assert "name (str, required)" in out
    assert "rounds (int" in out
    assert "default=5" in out
    assert "Hints are stored but not consumed." in out


def test_render_catalog_empty_returns_explicit_marker():
    from deerflow.workflows.prompt import render_workflow_catalog
    from deerflow.workflows.registry import WorkflowRegistry

    out = render_workflow_catalog(WorkflowRegistry(specs=[], failures=[]))
    assert "no workflows" in out.lower()


def test_render_catalog_omits_hint_section_when_doc_blank():
    from deerflow.workflows.prompt import render_workflow_catalog
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    reg = WorkflowRegistry(specs=[
        WorkflowSpec(
            name="x",
            description="d",
            factory=_factory,
            input_schema=_SampleInput,
            done_field="is_done",
            report_field="r",
        ),
    ], failures=[])
    out = render_workflow_catalog(reg)
    assert "Hint behavior" not in out
