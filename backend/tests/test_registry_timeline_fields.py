"""Tests for the progress_timeline_fields field on WorkflowSpec.

Drives the ProgressTimeline UI panel in the workflow detail page.
"""
from __future__ import annotations


def test_workflow_spec_carries_progress_timeline_fields():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "tl",
        "description": "d",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
        "progress_fields": ["current_round"],
        "progress_timeline_fields": ["history"],
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    spec = reg.get("tl")
    assert spec.progress_timeline_fields == ["history"]


def test_workflow_spec_progress_timeline_fields_defaults_empty():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "tl2",
        "description": "d",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    assert reg.get("tl2").progress_timeline_fields == []
