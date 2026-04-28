"""Lifespan registers WorkflowRegistry on app.state."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI


@asynccontextmanager
async def _noop_async_cm():
    yield None


@pytest.mark.asyncio
async def test_lifespan_attaches_workflow_registry(monkeypatch):
    """The langgraph_runtime context manager must populate app.state.workflow_registry.

    We patch the 3 heavy resource factories (checkpointer / store / stream bridge)
    with no-op async context managers so the lifespan runs end-to-end without
    needing a real config.yaml or backend services. We also stub
    WorkflowRegistry.load_from_app_config so we can assert on identity.
    """
    from deerflow import runtime as runtime_pkg
    from deerflow.agents.checkpointer import async_provider
    from deerflow.workflows.registry import WorkflowRegistry

    monkeypatch.setattr(async_provider, "make_checkpointer", _noop_async_cm)
    monkeypatch.setattr(runtime_pkg, "make_store", _noop_async_cm)
    monkeypatch.setattr(runtime_pkg, "make_stream_bridge", _noop_async_cm)

    fake_registry = WorkflowRegistry.load_from_dicts([])
    monkeypatch.setattr(
        WorkflowRegistry,
        "load_from_app_config",
        classmethod(lambda cls: fake_registry),
    )

    from app.gateway.deps import langgraph_runtime

    app = FastAPI()
    async with langgraph_runtime(app):
        assert getattr(app.state, "workflow_registry", None) is fake_registry


@pytest.mark.asyncio
async def test_lifespan_logs_when_registry_has_failures(monkeypatch, caplog):
    """If the registry reports failed workflows, lifespan emits a warning."""
    import logging

    from deerflow import runtime as runtime_pkg
    from deerflow.agents.checkpointer import async_provider
    from deerflow.workflows.registry import WorkflowRegistry

    monkeypatch.setattr(async_provider, "make_checkpointer", _noop_async_cm)
    monkeypatch.setattr(runtime_pkg, "make_store", _noop_async_cm)
    monkeypatch.setattr(runtime_pkg, "make_stream_bridge", _noop_async_cm)

    # Build a registry with one synthetic failure entry.
    fake_registry = WorkflowRegistry(specs=[], failures=[("bad-wf", "ImportError: nope")])
    monkeypatch.setattr(
        WorkflowRegistry,
        "load_from_app_config",
        classmethod(lambda cls: fake_registry),
    )

    from app.gateway.deps import langgraph_runtime

    app = FastAPI()
    with caplog.at_level(logging.WARNING, logger="app.gateway.deps"):
        async with langgraph_runtime(app):
            pass

    assert any("Workflow registry skipped" in rec.message for rec in caplog.records)
