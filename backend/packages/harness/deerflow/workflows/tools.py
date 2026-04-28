"""LLM-facing workflow platform tools.

Exposed to lead_agent via BUILTIN_TOOLS:
- start_workflow(name, params)
- inject_hint(thread_id, hint)        — added in Task 9
- cancel_workflow(thread_id)          — added in Task 10
- get_workflow_progress(thread_id)    — added in Task 11

The 3 thread-targeting tools validate that thread_id refers to a workflow
the platform actually started, to prevent accidental injection into chat
threads.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from pydantic import ValidationError

from deerflow.runtime.checkpointer_singleton import get_default_checkpointer
from deerflow.workflows.background import run_workflow_background
from deerflow.workflows.registry import WorkflowRegistry

logger = logging.getLogger(__name__)


# Module-level registries — populated by lifespan integration (Task 13).
# Tests monkeypatch ``_get_registry`` to inject a fake.
_REGISTRY: WorkflowRegistry | None = None
_BG_TASKS: dict[str, asyncio.Task] = {}
_THREAD_TO_WORKFLOW: dict[str, str] = {}  # child_thread_id -> workflow name


def set_registry(registry: WorkflowRegistry) -> None:
    """Install the process-wide WorkflowRegistry. Called from gateway lifespan."""
    global _REGISTRY
    _REGISTRY = registry


def _get_registry() -> WorkflowRegistry:
    if _REGISTRY is None:
        raise RuntimeError("WorkflowRegistry not set; call set_registry() at startup")
    return _REGISTRY


def _tool_msg(content: str, tool_call_id: str) -> Command:
    return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


def _parent_thread_id_from_config(config: RunnableConfig | None) -> str | None:
    if not config:
        return None
    return (config.get("configurable") or {}).get("thread_id")


@tool
async def start_workflow(
    name: str,
    params: dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> Command:
    """Start a registered workflow in the background.

    Args:
        name: Workflow name as registered in config.yaml workflows[].name.
        params: Arguments for the workflow's input_schema (Pydantic model).
            Missing required fields cause a tool error you should ask the
            user about and retry.

    Returns:
        Tool message with the new child thread_id; use it for inject_hint /
        cancel_workflow / get_workflow_progress.
    """
    registry = _get_registry()
    if not registry.has(name):
        available = ", ".join(registry.names()) or "(none)"
        return _tool_msg(
            f"Workflow {name!r} is not registered. Available: {available}",
            tool_call_id,
        )
    spec = registry.get(name)
    try:
        validated = spec.input_schema.model_validate(params)
    except ValidationError as ve:
        return _tool_msg(
            f"Invalid params for {name!r}:\n{ve.errors(include_url=False)}",
            tool_call_id,
        )

    parent_tid = _parent_thread_id_from_config(config)
    if not parent_tid:
        return _tool_msg(
            "start_workflow could not determine parent thread_id from config; refusing to start.",
            tool_call_id,
        )

    child_tid = str(uuid.uuid4())
    cp = get_default_checkpointer()

    task = asyncio.create_task(
        run_workflow_background(
            spec=spec,
            params=validated.model_dump(),
            child_thread_id=child_tid,
            parent_thread_id=parent_tid,
            checkpointer=cp,
        )
    )
    _BG_TASKS[child_tid] = task
    _THREAD_TO_WORKFLOW[child_tid] = name
    task.add_done_callback(lambda _t: _BG_TASKS.pop(child_tid, None))

    return _tool_msg(
        f"Started workflow {name!r}; thread_id={child_tid}. "
        f"Use get_workflow_progress / inject_hint / cancel_workflow to control it.",
        tool_call_id,
    )


@tool
async def inject_hint(
    thread_id: str,
    hint: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Append a free-text hint to a running workflow's inbox (non-blocking).

    The workflow decides when (and whether) to consume the hint. Multiple
    hints accumulate in order until the workflow chooses to clear them.

    Args:
        thread_id: child thread_id returned by start_workflow.
        hint: Free-text instruction; the workflow's behavior doc explains
            how it is interpreted.
    """
    if thread_id not in _THREAD_TO_WORKFLOW:
        return _tool_msg(
            f"thread_id={thread_id!r} is not a registered workflow thread; "
            f"refusing to inject (only platform-started workflows accept hints).",
            tool_call_id,
        )
    name = _THREAD_TO_WORKFLOW[thread_id]
    spec = _get_registry().get(name)
    cp = get_default_checkpointer()
    graph = spec.factory(checkpointer=cp)
    await graph.aupdate_state(
        config={"configurable": {"thread_id": thread_id}},
        values={"_hints": [hint]},
    )
    return _tool_msg(f"Hint injected into {name!r} (thread_id={thread_id}).", tool_call_id)
