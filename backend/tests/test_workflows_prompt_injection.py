"""Verifies the lead_agent system prompt includes the workflow catalog when a
registry is wired in."""

from __future__ import annotations


def test_apply_prompt_template_includes_catalog_when_registry_has_workflows(monkeypatch):
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    reg = WorkflowRegistry(specs=[WorkflowSpec(
        name="demo-flow",
        description="Zero-LLM pipeline used to validate the platform.",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
        progress_fields=["current_round"],
        hint_behavior_doc="Hints are stored but not consumed (no LLM nodes).",
    )], failures=[])
    monkeypatch.setattr(tools_mod, "_REGISTRY", reg)

    from deerflow.agents.lead_agent.prompt import apply_prompt_template

    out = apply_prompt_template()
    # Header from render_workflow_catalog
    assert "Available Workflows" in out
    # The workflow's name and description show up
    assert "demo-flow" in out
    assert "Zero-LLM pipeline" in out
    # Pydantic-derived params line
    assert "task_name" in out
    # Hint behavior line
    assert "Hints are stored but not consumed" in out


def test_apply_prompt_template_omits_catalog_when_registry_empty(monkeypatch):
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.registry import WorkflowRegistry

    reg = WorkflowRegistry(specs=[], failures=[])
    monkeypatch.setattr(tools_mod, "_REGISTRY", reg)

    from deerflow.agents.lead_agent.prompt import apply_prompt_template

    out = apply_prompt_template()
    assert "Available Workflows" not in out


def test_apply_prompt_template_omits_catalog_when_registry_none(monkeypatch):
    """If lifespan never ran, _REGISTRY is None — prompt builds without catalog."""
    from deerflow.workflows import tools as tools_mod

    monkeypatch.setattr(tools_mod, "_REGISTRY", None)

    from deerflow.agents.lead_agent.prompt import apply_prompt_template

    out = apply_prompt_template()
    assert "Available Workflows" not in out


def test_apply_prompt_template_swallows_catalog_errors(monkeypatch, caplog):
    """Catalog rendering errors must not break agent creation."""
    import logging

    from deerflow.workflows import prompt as wf_prompt
    from deerflow.workflows import tools as tools_mod

    class _Boom:
        def all(self):
            raise RuntimeError("synthetic")

    monkeypatch.setattr(tools_mod, "_REGISTRY", _Boom())
    monkeypatch.setattr(wf_prompt, "render_workflow_catalog", lambda r: r.all())

    from deerflow.agents.lead_agent.prompt import apply_prompt_template

    with caplog.at_level(logging.WARNING):
        out = apply_prompt_template()

    assert "Available Workflows" not in out
    # Defensive logging is nice but not strictly required;
    # the main contract is "doesn't blow up".
