"""Tests for POST /api/threads/{p}/workflows/{c}/messages."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_post_workflow_message_appends_human_message(monkeypatch):
    import deerflow.workflows.tools as wftools
    from app.gateway.routers.threads import post_workflow_message

    monkeypatch.setattr(
        wftools, "_THREAD_TO_WORKFLOW", {"c": "demo-flow"}, raising=False,
    )

    captured: dict = {}

    async def fake_inject(child_tid, content, *, checkpointer):
        captured["child_tid"] = child_tid
        captured["content"] = content

    import deerflow.workflows.emit as emit_mod
    monkeypatch.setattr(emit_mod, "inject_user_message_to_workflow", fake_inject)

    req = MagicMock()
    req.app.state.checkpointer = object()  # what get_checkpointer reads

    from pydantic import BaseModel

    class Body(BaseModel):
        content: str

    result = await post_workflow_message(
        "p", "c", body=Body(content="use dropout"), request=req,
    )

    assert result == {"ok": True}
    assert captured == {"child_tid": "c", "content": "use dropout"}


@pytest.mark.asyncio
async def test_post_workflow_message_404_for_unknown_child(monkeypatch):
    import deerflow.workflows.tools as wftools
    from app.gateway.routers.threads import post_workflow_message
    from fastapi import HTTPException

    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {}, raising=False)

    req = MagicMock()

    from pydantic import BaseModel

    class Body(BaseModel):
        content: str

    with pytest.raises(HTTPException) as exc:
        await post_workflow_message(
            "p", "ghost", body=Body(content="x"), request=req,
        )
    assert exc.value.status_code == 404
