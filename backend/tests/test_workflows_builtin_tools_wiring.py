"""Verifies that the 4 platform workflow tools are registered in BUILTIN_TOOLS
and that set_registry is called from lifespan.
"""

from __future__ import annotations

import pytest


def test_builtin_tools_includes_4_workflow_tools():
    """The lead_agent's BUILTIN_TOOLS list must include all 4 platform tools."""
    from deerflow.tools.tools import BUILTIN_TOOLS
    from deerflow.workflows.tools import (
        cancel_workflow,
        get_workflow_progress,
        inject_hint,
        start_workflow,
    )

    names = {getattr(t, "name", None) for t in BUILTIN_TOOLS}
    assert "start_workflow" in names
    assert "inject_hint" in names
    assert "cancel_workflow" in names
    assert "get_workflow_progress" in names

    assert start_workflow in BUILTIN_TOOLS
    assert inject_hint in BUILTIN_TOOLS
    assert cancel_workflow in BUILTIN_TOOLS
    assert get_workflow_progress in BUILTIN_TOOLS


@pytest.mark.asyncio
async def test_lifespan_calls_set_registry_on_workflow_tools_module(monkeypatch):
    """When lifespan loads the registry, it must wire it into the tools module."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from deerflow import runtime as runtime_pkg
    from deerflow.agents.checkpointer import async_provider
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.registry import WorkflowRegistry

    @asynccontextmanager
    async def _noop_async_cm():
        yield None

    monkeypatch.setattr(async_provider, "make_checkpointer", _noop_async_cm)
    monkeypatch.setattr(runtime_pkg, "make_store", _noop_async_cm)
    monkeypatch.setattr(runtime_pkg, "make_stream_bridge", _noop_async_cm)

    fake_registry = WorkflowRegistry.load_from_dicts([])
    monkeypatch.setattr(
        WorkflowRegistry,
        "load_from_app_config",
        classmethod(lambda cls: fake_registry),
    )

    # Reset module-level _REGISTRY before the lifespan runs
    monkeypatch.setattr(tools_mod, "_REGISTRY", None)

    from app.gateway.deps import langgraph_runtime

    app = FastAPI()
    async with langgraph_runtime(app):
        # Inside the lifespan, _REGISTRY should now be set to fake_registry
        assert tools_mod._REGISTRY is fake_registry
        # And _get_registry() should return it
        assert tools_mod._get_registry() is fake_registry
