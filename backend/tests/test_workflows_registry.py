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
