"""Workflow Hub aggregation endpoint.

Surfaces all workflows the user has ever started, grouped by their parent
thread. Walks the Store for parent thread records, filters to those with
non-empty ``metadata.child_workflow_threads``, then loads each child's
checkpoint from the checkpointer to derive a (status, progress, report)
snapshot.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.gateway.deps import get_checkpointer, get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows-hub"])

THREADS_NS = ("threads",)
_REPORT_PREVIEW_LEN = 240
_ERROR_PREVIEW_LEN = 240


def _classify_status(values: dict, done_field: str) -> tuple[str, str | None]:
    """Return (status, error_string).

    status ∈ {"running", "done", "failed", "cancelled"}.
    """
    error = values.get("_error")
    is_done = bool(values.get(done_field))
    if error and isinstance(error, str):
        if error.startswith("CancelledError"):
            return "cancelled", error
        return "failed", error
    if is_done:
        return "done", None
    return "running", None


def _truncate(s: str | None, limit: int) -> str | None:
    if not s:
        return None
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


@router.get("/all")
async def list_all_workflows(request: Request) -> dict:
    """List every workflow grouped by parent thread.

    Returns ``{"parents": [{thread_id, title, created_at, workflows: [...]}]}``.

    Only parent threads with at least one entry in
    ``metadata.child_workflow_threads`` appear. Children whose checkpoint
    is missing (e.g. unfinished startup, gateway restart loss) are
    classified ``running`` with empty progress; the frontend can still
    render them with a "(no state available)" hint.
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)

    if store is None:
        return {"parents": []}

    # Lazy imports to avoid pulling workflow tooling into the gateway's
    # bare import graph.
    from deerflow.workflows.tools import _BG_TASKS, _THREAD_TO_WORKFLOW, _get_registry

    try:
        registry = _get_registry()
    except RuntimeError:
        return {"parents": []}

    # Walk Store for parent records
    try:
        items = await store.asearch(THREADS_NS, limit=10000)
    except Exception:
        logger.exception("workflows-hub: store.asearch failed")
        return {"parents": []}

    parents_out: list[dict] = []

    for item in items:
        record = getattr(item, "value", None) or {}
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") or {}
        children = metadata.get("child_workflow_threads") or []
        if not children:
            continue

        parent_thread_id = record.get("thread_id") or getattr(item, "key", None)
        if not parent_thread_id:
            continue

        wf_entries: list[dict] = []
        for entry in children:
            if not isinstance(entry, dict):
                continue
            child_tid = entry.get("thread_id")
            wf_name = entry.get("name") or _THREAD_TO_WORKFLOW.get(child_tid or "")
            if not child_tid or not wf_name:
                continue
            try:
                spec = registry.get(wf_name)
            except KeyError:
                # Workflow registered when started, since unregistered
                wf_entries.append({
                    "child_thread_id": child_tid,
                    "name": wf_name,
                    "status": "running",  # unknown — best guess
                    "started_at": entry.get("started_at"),
                    "finished_at": None,
                    "progress": {},
                    "progress_timeline_fields": [],
                    "report_field": None,
                    "report_preview": None,
                    "error": "workflow spec not registered",
                })
                continue

            cp_tuple = None
            try:
                cp_tuple = await checkpointer.aget_tuple(
                    {"configurable": {"thread_id": child_tid, "checkpoint_ns": ""}},
                )
            except Exception:
                logger.warning(
                    "workflows-hub: checkpoint load failed for %s", child_tid,
                    exc_info=True,
                )

            # No checkpoint AND not currently in flight → the child was
            # deleted (DELETE /api/threads/{cid}) but the parent's
            # metadata still references it. Skip — it should not appear
            # in the hub.
            if cp_tuple is None and child_tid not in _BG_TASKS:
                continue

            values = {}
            if cp_tuple is not None:
                values = (cp_tuple.checkpoint or {}).get("channel_values", {}) or {}

            status, error = _classify_status(values, spec.done_field)
            progress = {f: values[f] for f in spec.progress_fields if f in values}
            report = values.get(spec.report_field) if status == "done" else None

            wf_entries.append({
                "child_thread_id": child_tid,
                "name": wf_name,
                "status": status,
                "started_at": entry.get("started_at"),
                "finished_at": (
                    None if status == "running"
                    else (record.get("updated_at") or entry.get("started_at"))
                ),
                "progress": progress,
                "progress_timeline_fields": list(spec.progress_timeline_fields),
                "report_field": spec.report_field,
                "report_preview": _truncate(report, _REPORT_PREVIEW_LEN),
                "error": _truncate(error, _ERROR_PREVIEW_LEN),
            })

        if not wf_entries:
            continue

        # Title lives in the thread record's `values.title` (written by
        # TitleMiddleware after the first turn). Older / out-of-band
        # store writes may put it under `metadata.title` instead.
        values = record.get("values") or {}
        title = (
            values.get("title") if isinstance(values, dict) else None
        ) or record.get("metadata", {}).get("title")
        parents_out.append({
            "thread_id": parent_thread_id,
            "title": title,
            "created_at": record.get("created_at"),
            "workflows": wf_entries,
        })

    # Sort parents by created_at desc (Q1=b)
    parents_out.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return {"parents": parents_out}
