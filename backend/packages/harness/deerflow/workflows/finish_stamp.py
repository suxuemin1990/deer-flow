"""Stamp recent_workflow_finish_at on a parent thread's store metadata.

Called by the workflow background runner whenever a child workflow reaches
a terminal state (success / failure / cancel). The frontend uses the
timestamp to decide whether the parent thread's chat-list item should
show an "unread workflow finish" red dot.

Best-effort: any error here (store missing, parent record absent,
serialization failure) is logged and swallowed — must never block the
emit path or crash the bg task.
"""

from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)

THREADS_NS = ("threads",)


async def stamp_parent_finish(parent_thread_id: str) -> None:
    try:
        from deerflow.runtime.store_singleton import get_default_store

        store = get_default_store()
        if store is None:
            return

        now_iso = datetime.datetime.now(datetime.UTC).isoformat()

        existing = await store.aget(THREADS_NS, parent_thread_id)
        existing_value = (existing.value if existing is not None else {}) or {}
        metadata = dict(existing_value.get("metadata") or {})

        prev = metadata.get("recent_workflow_finish_at")
        if prev is None or now_iso > prev:
            metadata["recent_workflow_finish_at"] = now_iso

        new_record = dict(existing_value) if existing_value else {
            "thread_id": parent_thread_id,
            "status": "idle",
            "created_at": now_iso,
            "values": {},
        }
        new_record["thread_id"] = parent_thread_id
        new_record["metadata"] = metadata
        new_record["updated_at"] = now_iso
        new_record.setdefault("status", "idle")
        new_record.setdefault("created_at", now_iso)
        new_record.setdefault("values", {})

        await store.aput(THREADS_NS, parent_thread_id, new_record)
    except Exception:
        logger.warning(
            "could not stamp recent_workflow_finish_at on parent=%s",
            parent_thread_id, exc_info=True,
        )
