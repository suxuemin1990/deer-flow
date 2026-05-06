"""Verify SystemPromptPathMiddleware substitutes path placeholders at model-call time."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import SystemMessage

from deerflow.agents.middlewares.system_prompt_path_middleware import (
    SystemPromptPathMiddleware,
)


def _make_request(system_content: str | None, thread_data: dict | None):
    """Construct a ModelRequest-shaped object the middleware will accept.

    The middleware reads .system_message and .state and calls .override(...).
    A SimpleNamespace with the right attributes is enough — we don't run a real model.
    """
    sm = SystemMessage(content=system_content) if system_content is not None else None
    state = {"thread_data": thread_data} if thread_data is not None else {}
    request = SimpleNamespace(system_message=sm, state=state)

    def override(**kwargs):
        new_sm = kwargs.get("system_message", request.system_message)
        new_req = SimpleNamespace(system_message=new_sm, state=request.state)
        new_req.override = override  # type: ignore[attr-defined]
        return new_req

    request.override = override  # type: ignore[attr-defined]
    return request


def test_substitutes_placeholders_when_thread_data_present():
    request = _make_request(
        system_content="workspace at {workspace_path} and uploads at {uploads_path}",
        thread_data={"workspace_path": "/ws", "uploads_path": "/up", "outputs_path": "/out"},
    )
    middleware = SystemPromptPathMiddleware()

    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert captured["req"].system_message.content == "workspace at /ws and uploads at /up"


def test_skips_when_no_placeholders():
    request = _make_request(
        system_content="No placeholders here",
        thread_data={"workspace_path": "/ws"},
    )
    middleware = SystemPromptPathMiddleware()
    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert captured["req"] is request


def test_skips_when_thread_data_absent():
    request = _make_request(
        system_content="workspace at {workspace_path}",
        thread_data=None,
    )
    middleware = SystemPromptPathMiddleware()
    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert captured["req"] is request
    # Content unchanged (placeholder still raw — middleware can fire later).
    assert captured["req"].system_message.content == "workspace at {workspace_path}"


def test_skips_when_thread_data_empty():
    request = _make_request(
        system_content="workspace at {workspace_path}",
        thread_data={},
    )
    middleware = SystemPromptPathMiddleware()
    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert captured["req"] is request


def test_preserves_unknown_placeholders():
    """SafeFormatDict leaves {unknown_key} intact."""
    request = _make_request(
        system_content="ws={workspace_path} other={unknown_key}",
        thread_data={"workspace_path": "/ws"},
    )
    middleware = SystemPromptPathMiddleware()
    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    out = captured["req"].system_message.content
    assert "{unknown_key}" in out
    assert "/ws" in out


def test_skips_when_system_message_missing():
    request = _make_request(system_content=None, thread_data={"workspace_path": "/ws"})
    middleware = SystemPromptPathMiddleware()
    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    assert captured["req"] is request


def test_substitutes_only_present_keys():
    """Only placeholders whose thread_data values are present get substituted;
    missing ones remain raw (so a later turn can fill them)."""
    request = _make_request(
        system_content="ws={workspace_path} up={uploads_path}",
        thread_data={"workspace_path": "/ws"},  # uploads_path absent
    )
    middleware = SystemPromptPathMiddleware()
    captured = {}

    def handler(req):
        captured["req"] = req
        return MagicMock()

    middleware.wrap_model_call(request, handler)
    out = captured["req"].system_message.content
    assert out == "ws=/ws up={uploads_path}"


@pytest.mark.asyncio
async def test_async_substitutes_placeholders():
    request = _make_request(
        system_content="ws={workspace_path}",
        thread_data={"workspace_path": "/async-ws"},
    )
    middleware = SystemPromptPathMiddleware()
    captured = {}

    async def handler(req):
        captured["req"] = req
        return MagicMock()

    await middleware.awrap_model_call(request, handler)
    assert captured["req"].system_message.content == "ws=/async-ws"
