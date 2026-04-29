"""Unit tests for the workflow registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel


class _FakeInput(BaseModel):
    name: str
    rounds: int = 5


def _fake_factory(checkpointer=None):  # noqa: ARG001
    return "fake-graph"


def test_workflow_spec_dataclass_fields():
    from deerflow.workflows.registry import WorkflowSpec

    spec = WorkflowSpec(
        name="demo",
        description="d",
        factory=_fake_factory,
        input_schema=_FakeInput,
        done_field="is_done",
        report_field="report",
        progress_fields=["round"],
        hint_behavior_doc="hb",
    )
    assert spec.name == "demo"
    assert spec.factory is _fake_factory
    assert spec.input_schema is _FakeInput
    assert spec.progress_fields == ["round"]


def test_registry_load_from_dicts_succeeds(monkeypatch):
    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    monkeypatch.setattr(reg_mod, "_resolve", lambda spec: {
        "deerflow.fake:_fake_factory": _fake_factory,
        "deerflow.fake:_FakeInput": _FakeInput,
    }[spec])

    registry = WorkflowRegistry.load_from_dicts([{
        "name": "demo",
        "description": "d",
        "factory": "deerflow.fake:_fake_factory",
        "input_schema": "deerflow.fake:_FakeInput",
        "done_field": "is_done",
        "report_field": "report",
    }])

    assert "demo" in registry.names()
    spec = registry.get("demo")
    assert spec.factory is _fake_factory
    assert spec.input_schema is _FakeInput
    assert spec.progress_fields == []
    assert spec.hint_behavior_doc == ""


def test_registry_load_skips_failures(monkeypatch, caplog):
    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    def fake_resolve(spec):
        if "broken" in spec:
            raise ImportError(f"cannot import {spec}")
        return {
            "deerflow.fake:_fake_factory": _fake_factory,
            "deerflow.fake:_FakeInput": _FakeInput,
        }[spec]

    monkeypatch.setattr(reg_mod, "_resolve", fake_resolve)

    registry = WorkflowRegistry.load_from_dicts([
        {
            "name": "good",
            "description": "ok",
            "factory": "deerflow.fake:_fake_factory",
            "input_schema": "deerflow.fake:_FakeInput",
            "done_field": "d",
            "report_field": "r",
        },
        {
            "name": "bad",
            "description": "broken",
            "factory": "deerflow.broken:nope",
            "input_schema": "deerflow.fake:_FakeInput",
            "done_field": "d",
            "report_field": "r",
        },
    ])

    assert registry.names() == ["good"]
    assert registry.failed() == [("bad", "ImportError: cannot import deerflow.broken:nope")]


def test_registry_get_unknown_raises():
    from deerflow.workflows.registry import WorkflowRegistry

    registry = WorkflowRegistry.load_from_dicts([])
    with pytest.raises(KeyError):
        registry.get("nope")


def test_registry_input_schema_must_be_basemodel(monkeypatch):
    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    class NotPydantic:
        pass

    monkeypatch.setattr(reg_mod, "_resolve", lambda spec: {
        "deerflow.fake:_fake_factory": _fake_factory,
        "deerflow.fake:NotPydantic": NotPydantic,
    }[spec])

    registry = WorkflowRegistry.load_from_dicts([{
        "name": "bad-schema",
        "description": "d",
        "factory": "deerflow.fake:_fake_factory",
        "input_schema": "deerflow.fake:NotPydantic",
        "done_field": "d",
        "report_field": "r",
    }])
    assert registry.names() == []
    assert "bad-schema" in dict(registry.failed())


def test_load_from_app_config_picks_up_workflows_section(monkeypatch):
    """If get_app_config() returns an object with .workflows, registry picks them up."""
    from types import SimpleNamespace

    from deerflow.workflows.registry import WorkflowRegistry

    fake_cfg = SimpleNamespace(workflows=[{
        "name": "demo-flow",
        "description": "demo",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
    }])
    import deerflow.config as deerflow_config
    monkeypatch.setattr(deerflow_config, "get_app_config", lambda: fake_cfg)

    registry = WorkflowRegistry.load_from_app_config()
    assert "demo-flow" in registry.names()
    assert registry.get("demo-flow").factory.__name__ == "make_graph"


def test_load_from_app_config_handles_missing_workflows_attr(monkeypatch):
    """When the config has no .workflows attribute, registry is empty (not an error)."""
    from types import SimpleNamespace

    from deerflow.workflows.registry import WorkflowRegistry

    fake_cfg = SimpleNamespace()  # no workflows attr
    import deerflow.config as deerflow_config
    monkeypatch.setattr(deerflow_config, "get_app_config", lambda: fake_cfg)

    registry = WorkflowRegistry.load_from_app_config()
    assert registry.names() == []
    assert registry.failed() == []


def test_workflow_spec_accepts_chat_defaults_false():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "demo",
        "description": "x",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    spec = reg.get("demo")
    assert spec.accepts_chat is False


def test_workflow_spec_accepts_chat_explicit_true():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "demo",
        "description": "x",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
        "accepts_chat": True,
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    assert reg.get("demo").accepts_chat is True
