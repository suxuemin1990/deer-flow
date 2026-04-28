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
import json
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

    await _record_child_workflow_thread(parent_tid, child_tid, name)

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


@tool
async def cancel_workflow(
    thread_id: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Cancel a running workflow.

    Sends asyncio CancelledError to the background task. The current node
    is interrupted; state rolls back to the previous checkpoint. ``_error``
    and ``done_field`` are set on the child state. A failure message is
    emitted to the parent thread.
    """
    if thread_id not in _THREAD_TO_WORKFLOW:
        return _tool_msg(
            f"thread_id={thread_id!r} is not a registered workflow thread.",
            tool_call_id,
        )
    name = _THREAD_TO_WORKFLOW[thread_id]
    task = _BG_TASKS.get(thread_id)
    if task is None or task.done():
        return _tool_msg(
            f"Workflow {name!r} on thread {thread_id} is no longer running.",
            tool_call_id,
        )
    task.cancel()
    return _tool_msg(
        f"Cancellation signal sent to {name!r} (thread_id={thread_id}).",
        tool_call_id,
    )


@tool
async def get_workflow_progress(
    thread_id: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Return current progress of a running workflow.

    Includes platform fields (_hints / _error / done_field) and the
    workflow's declared progress_fields. When the workflow is done the
    report_field is included too.
    """
    if thread_id not in _THREAD_TO_WORKFLOW:
        return _tool_msg(
            f"thread_id={thread_id!r} is not a registered workflow thread.",
            tool_call_id,
        )
    name = _THREAD_TO_WORKFLOW[thread_id]
    spec = _get_registry().get(name)
    cp = get_default_checkpointer()
    graph = spec.factory(checkpointer=cp)
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = state.values or {}

    payload: dict[str, Any] = {
        "workflow": name,
        "thread_id": thread_id,
        spec.done_field: values.get(spec.done_field, False),
        "_hints": values.get("_hints") or [],
        "_error": values.get("_error"),
    }
    for fname in spec.progress_fields:
        if fname in values:
            payload[fname] = values[fname]
    if values.get(spec.done_field):
        payload[spec.report_field] = values.get(spec.report_field)

    return _tool_msg(json.dumps(payload, ensure_ascii=False, indent=2), tool_call_id)


async def _record_child_workflow_thread(
    parent_thread_id: str,
    child_thread_id: str,
    name: str,
) -> None:
    """Append a child workflow thread record to the parent thread's store metadata.

    Best-effort: any error here (store missing, parent thread record absent,
    serialization failure) is logged and swallowed — it must not prevent the
    background task from running.
    """
    try:
        import datetime

        from deerflow.runtime.store_singleton import get_default_store

        store = get_default_store()
        if store is None:
            return

        THREADS_NS = ("threads",)
        existing = await store.aget(THREADS_NS, parent_thread_id)
        existing_value = (existing.value if existing is not None else {}) or {}
        metadata = dict(existing_value.get("metadata") or {})
        children = list(metadata.get("child_workflow_threads") or [])
        children.append({
            "thread_id": child_thread_id,
            "name": name,
            "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
        })
        metadata["child_workflow_threads"] = children

        now = datetime.datetime.now(datetime.UTC).isoformat()
        new_record = dict(existing_value) if existing_value else {
            "thread_id": parent_thread_id,
            "status": "idle",
            "created_at": now,
            "values": {},
        }
        new_record["thread_id"] = parent_thread_id
        new_record["metadata"] = metadata
        new_record["updated_at"] = now
        new_record.setdefault("status", "idle")
        new_record.setdefault("created_at", now)
        new_record.setdefault("values", {})
        await store.aput(THREADS_NS, parent_thread_id, new_record)
    except Exception:
        logger.warning(
            "could not record child workflow thread for parent=%s child=%s",
            parent_thread_id, child_thread_id, exc_info=True,
        )
