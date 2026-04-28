"""Gateway lifespan registers the default RunManager singleton.

This is the bridge between the gateway-owned ``RunManager`` (which already
lives on ``app.state.run_manager``) and background workflow tasks running
in graph nodes that have no Request handle.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI


@asynccontextmanager
async def _noop_async_cm():
    yield None


@pytest.mark.asyncio
async def test_lifespan_registers_default_run_manager(monkeypatch):
    from deerflow import runtime as runtime_pkg
    from deerflow.agents.checkpointer import async_provider
    from deerflow.runtime.run_manager_singleton import (
        reset_default_run_manager,
        try_get_default_run_manager,
    )
    from deerflow.workflows.registry import WorkflowRegistry

    reset_default_run_manager()

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

    # Before lifespan: nothing registered.
    assert try_get_default_run_manager() is None

    app = FastAPI()
    async with langgraph_runtime(app):
        # Inside lifespan: same instance as on app.state.run_manager.
        assert try_get_default_run_manager() is app.state.run_manager

    reset_default_run_manager()
