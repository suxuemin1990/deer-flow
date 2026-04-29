"""Thread CRUD, state, and history endpoints.

Combines the existing thread-local filesystem cleanup with LangGraph
Platform-compatible thread management backed by the checkpointer.

Channel values returned in state responses are serialized through
:func:`deerflow.runtime.serialization.serialize_channel_values` to
ensure LangChain message objects are converted to JSON-safe dicts
matching the LangGraph Platform wire format expected by the
``useStream`` React hook.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_checkpointer, get_store
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime import serialize_channel_values


def _iso_now() -> str:
    """Return current UTC time as an ISO-8601 string with ``Z`` suffix.

    LangGraph Server protocol returns timestamps in this exact format and
    the frontend (date-fns ``formatDistanceToNow``) parses them via
    ``new Date(...)``.  Using raw epoch floats / strings here causes
    ``Invalid Date`` and crashes the chats list page.
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_iso(value: Any) -> str:
    """Coerce a stored timestamp to ISO-8601 (with ``Z`` suffix).

    Accepts ISO strings (returned as-is), epoch ints/floats, and numeric
    strings (legacy records written before this helper existed).  Empty
    or unparseable values yield ``""``.
    """
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
    s = str(value)
    # Legacy records stored ``str(time.time())`` — parse the float back.
    try:
        ts = float(s)
    except (ValueError, TypeError):
        return s  # already an ISO-ish string, return as-is
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Store namespace
# ---------------------------------------------------------------------------

THREADS_NS: tuple[str, ...] = ("threads",)
"""Namespace used by the Store for thread metadata records."""

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class ThreadDeleteResponse(BaseModel):
    """Response model for thread cleanup."""

    success: bool
    message: str


class ThreadResponse(BaseModel):
    """Response model for a single thread."""

    thread_id: str = Field(description="Unique thread identifier")
    status: str = Field(default="idle", description="Thread status: idle, busy, interrupted, error")
    created_at: str = Field(default="", description="ISO timestamp")
    updated_at: str = Field(default="", description="ISO timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Thread metadata")
    values: dict[str, Any] = Field(default_factory=dict, description="Current state channel values")
    interrupts: dict[str, Any] = Field(default_factory=dict, description="Pending interrupts")


class ThreadCreateRequest(BaseModel):
    """Request body for creating a thread."""

    thread_id: str | None = Field(default=None, description="Optional thread ID (auto-generated if omitted)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Initial metadata")


class ThreadSearchRequest(BaseModel):
    """Request body for searching threads."""

    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata filter (exact match)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    status: str | None = Field(default=None, description="Filter by thread status")


class ThreadStateResponse(BaseModel):
    """Response model for thread state."""

    values: dict[str, Any] = Field(default_factory=dict, description="Current channel values")
    next: list[str] = Field(default_factory=list, description="Next tasks to execute")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Checkpoint metadata")
    checkpoint: dict[str, Any] = Field(default_factory=dict, description="Checkpoint info")
    checkpoint_id: str | None = Field(default=None, description="Current checkpoint ID")
    parent_checkpoint_id: str | None = Field(default=None, description="Parent checkpoint ID")
    created_at: str | None = Field(default=None, description="Checkpoint timestamp")
    tasks: list[dict[str, Any]] = Field(default_factory=list, description="Interrupted task details")


class ThreadPatchRequest(BaseModel):
    """Request body for patching thread metadata."""

    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata to merge")


class ThreadStateUpdateRequest(BaseModel):
    """Request body for updating thread state (human-in-the-loop resume)."""

    values: dict[str, Any] | None = Field(default=None, description="Channel values to merge")
    checkpoint_id: str | None = Field(default=None, description="Checkpoint to branch from")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    as_node: str | None = Field(default=None, description="Node identity for the update")


class HistoryEntry(BaseModel):
    """Single checkpoint history entry."""

    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    next: list[str] = Field(default_factory=list)


class ThreadHistoryRequest(BaseModel):
    """Request body for checkpoint history."""

    limit: int = Field(default=10, ge=1, le=100, description="Maximum entries")
    before: str | None = Field(default=None, description="Cursor for pagination")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_thread_data(thread_id: str, paths: Paths | None = None) -> ThreadDeleteResponse:
    """Delete local persisted filesystem data for a thread."""
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError:
        # Not critical — thread data may not exist on disk
        logger.debug("No local thread data to delete for %s", thread_id)
        return ThreadDeleteResponse(success=True, message=f"No local data for {thread_id}")
    except Exception as exc:
        logger.exception("Failed to delete thread data for %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to delete local thread data.") from exc

    logger.info("Deleted local thread data for %s", thread_id)
    return ThreadDeleteResponse(success=True, message=f"Deleted local thread data for {thread_id}")


async def _store_get(store, thread_id: str) -> dict | None:
    """Fetch a thread record from the Store; returns ``None`` if absent."""
    item = await store.aget(THREADS_NS, thread_id)
    return item.value if item is not None else None


async def _store_put(store, record: dict) -> None:
    """Write a thread record to the Store."""
    await store.aput(THREADS_NS, record["thread_id"], record)


async def _store_upsert(store, thread_id: str, *, metadata: dict | None = None, values: dict | None = None) -> None:
    """Create or refresh a thread record in the Store.

    On creation the record is written with ``status="idle"``.  On update only
    ``updated_at`` (and optionally ``metadata`` / ``values``) are changed so
    that existing fields are preserved.

    ``values`` carries the agent-state snapshot exposed to the frontend
    (currently just ``{"title": "..."}``).
    """
    now = _iso_now()
    existing = await _store_get(store, thread_id)
    if existing is None:
        await _store_put(
            store,
            {
                "thread_id": thread_id,
                "status": "idle",
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or {},
                "values": values or {},
            },
        )
    else:
        val = dict(existing)
        val["updated_at"] = now
        if metadata:
            val.setdefault("metadata", {}).update(metadata)
        if values:
            val.setdefault("values", {}).update(values)
        await _store_put(store, val)


def _derive_thread_status(checkpoint_tuple) -> str:
    """Derive thread status from checkpoint metadata."""
    if checkpoint_tuple is None:
        return "idle"
    pending_writes = getattr(checkpoint_tuple, "pending_writes", None) or []

    # Check for error in pending writes
    for pw in pending_writes:
        if len(pw) >= 2 and pw[1] == "__error__":
            return "error"

    # Check for pending next tasks (indicates interrupt)
    tasks = getattr(checkpoint_tuple, "tasks", None)
    if tasks:
        return "interrupted"

    return "idle"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


async def _purge_thread(thread_id: str, store, checkpointer) -> None:
    """Best-effort full cleanup for a single thread (fs + store + checkpointer).

    Used for both the parent thread being deleted and each of its child
    workflow threads. Per-step failures are logged and swallowed so a single
    bad child does not abort the cascade.
    """
    # Filesystem.
    try:
        _delete_thread_data(thread_id)
    except HTTPException as exc:
        # Invalid thread_id (422) or fs failure (500) — log and continue so
        # cascade keeps going. The parent-level handler validates its own id
        # via the route.
        logger.warning(
            "Cascade cleanup: skipping fs delete for %s (%s)", thread_id, exc.detail
        )
    except Exception:
        logger.debug("Cascade cleanup: fs delete failed for %s", thread_id, exc_info=True)

    # Store record.
    if store is not None:
        try:
            await store.adelete(THREADS_NS, thread_id)
        except Exception:
            logger.debug(
                "Cascade cleanup: store delete failed for %s (not critical)", thread_id
            )

    # Checkpointer.
    if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
        try:
            await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.debug(
                "Cascade cleanup: checkpoint delete failed for %s (not critical)",
                thread_id,
            )


def _extract_child_thread_ids(metadata: dict | None) -> list[str]:
    """Pull child workflow thread ids from a parent record's metadata.

    Tolerates malformed entries (non-dict, missing thread_id) silently — same
    contract as ``_filter_workflow_child_threads`` in /threads/search.
    """
    if not metadata:
        return []
    children = metadata.get("child_workflow_threads")
    if not isinstance(children, list):
        return []
    out: list[str] = []
    for entry in children:
        if not isinstance(entry, dict):
            continue
        tid = entry.get("thread_id")
        if isinstance(tid, str) and tid:
            out.append(tid)
    return out


@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
async def delete_thread_data(thread_id: str, request: Request) -> ThreadDeleteResponse:
    """Delete a thread and all of its child workflow threads.

    Cleans DeerFlow-managed thread directories, removes checkpoint data, and
    removes the thread record from the Store — for the parent thread *and*
    for every child listed in the parent's ``metadata.child_workflow_threads``.

    Without the cascade, child workflow threads (which are filtered out of
    /threads/search by design) become invisible orphans on disk and in the
    checkpointer.
    """
    store = get_store(request)
    checkpointer = getattr(request.app.state, "checkpointer", None)

    # Read parent metadata BEFORE deleting it so we know which children
    # to cascade into.
    child_ids: list[str] = []
    if store is not None:
        try:
            record = await _store_get(store, thread_id)
        except Exception:
            logger.debug(
                "Cascade cleanup: failed to read parent record %s", thread_id, exc_info=True
            )
            record = None
        child_ids = _extract_child_thread_ids((record or {}).get("metadata"))

    # Clean parent fs first — this validates the thread_id (raises 422 on
    # path-traversal attempts) so callers get a clear error before we touch
    # store / checkpointer / children.
    response = _delete_thread_data(thread_id)

    # Cascade into children (best-effort).
    for child_id in child_ids:
        await _purge_thread(child_id, store, checkpointer)

    # Remove parent's own store record (best-effort).
    if store is not None:
        try:
            await store.adelete(THREADS_NS, thread_id)
        except Exception:
            logger.debug("Could not delete store record for thread %s (not critical)", thread_id)

    # Remove parent's checkpoints (best-effort).
    if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
        try:
            await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.debug("Could not delete checkpoints for thread %s (not critical)", thread_id)

    return response


@router.post("", response_model=ThreadResponse)
async def create_thread(body: ThreadCreateRequest, request: Request) -> ThreadResponse:
    """Create a new thread.

    The thread record is written to the Store (for fast listing) and an
    empty checkpoint is written to the checkpointer (for state reads).
    Idempotent: returns the existing record when ``thread_id`` already exists.
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)
    thread_id = body.thread_id or str(uuid.uuid4())
    now = _iso_now()

    # Idempotency: return existing record from Store when already present
    if store is not None:
        existing_record = await _store_get(store, thread_id)
        if existing_record is not None:
            return ThreadResponse(
                thread_id=thread_id,
                status=existing_record.get("status", "idle"),
                created_at=_to_iso(existing_record.get("created_at")),
                updated_at=_to_iso(existing_record.get("updated_at")),
                metadata=existing_record.get("metadata", {}),
            )

    # Write thread record to Store
    if store is not None:
        try:
            await _store_put(
                store,
                {
                    "thread_id": thread_id,
                    "status": "idle",
                    "created_at": now,
                    "updated_at": now,
                    "metadata": body.metadata,
                },
            )
        except Exception:
            logger.exception("Failed to write thread %s to store", thread_id)
            raise HTTPException(status_code=500, detail="Failed to create thread")

    # Write an empty checkpoint so state endpoints work immediately
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        from langgraph.checkpoint.base import empty_checkpoint

        ckpt_metadata = {
            "step": -1,
            "source": "input",
            "writes": None,
            "parents": {},
            **body.metadata,
            "created_at": now,
        }
        await checkpointer.aput(config, empty_checkpoint(), ckpt_metadata, {})
    except Exception:
        logger.exception("Failed to create checkpoint for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to create thread")

    logger.info("Thread created: %s", thread_id)
    return ThreadResponse(
        thread_id=thread_id,
        status="idle",
        created_at=now,
        updated_at=now,
        metadata=body.metadata,
    )


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(body: ThreadSearchRequest, request: Request) -> list[ThreadResponse]:
    """Search and list threads.

    Two-phase approach:

    **Phase 1 — Store (fast path, O(threads))**: returns threads that were
    created or run through this Gateway.  Store records are tiny metadata
    dicts so fetching all of them at once is cheap.

    **Phase 2 — Checkpointer supplement (lazy migration)**: threads that
    were created directly by LangGraph Server (and therefore absent from the
    Store) are discovered here by iterating the shared checkpointer.  Any
    newly found thread is immediately written to the Store so that the next
    search skips Phase 2 for that thread — the Store converges to a full
    index over time without a one-shot migration job.
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)

    # -----------------------------------------------------------------------
    # Phase 1: Store
    # -----------------------------------------------------------------------
    merged: dict[str, ThreadResponse] = {}

    if store is not None:
        try:
            items = await store.asearch(THREADS_NS, limit=10_000)
        except Exception:
            logger.warning("Store search failed — falling back to checkpointer only", exc_info=True)
            items = []

        for item in items:
            val = item.value
            merged[val["thread_id"]] = ThreadResponse(
                thread_id=val["thread_id"],
                status=val.get("status", "idle"),
                created_at=_to_iso(val.get("created_at")),
                updated_at=_to_iso(val.get("updated_at")),
                metadata=val.get("metadata", {}),
                values=val.get("values", {}),
            )

    # -----------------------------------------------------------------------
    # Phase 2: Checkpointer supplement
    # Discovers threads not yet in the Store (e.g. created by LangGraph
    # Server) and lazily migrates them so future searches skip this phase.
    # -----------------------------------------------------------------------
    try:
        async for checkpoint_tuple in checkpointer.alist(None):
            cfg = getattr(checkpoint_tuple, "config", {})
            thread_id = cfg.get("configurable", {}).get("thread_id")
            if not thread_id or thread_id in merged:
                continue

            # Skip sub-graph checkpoints (checkpoint_ns is non-empty for those)
            if cfg.get("configurable", {}).get("checkpoint_ns", ""):
                continue

            ckpt_meta = getattr(checkpoint_tuple, "metadata", {}) or {}
            # Strip LangGraph internal keys from the user-visible metadata dict
            user_meta = {k: v for k, v in ckpt_meta.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")}

            # Extract state values (title) from the checkpoint's channel_values
            checkpoint_data = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint_data.get("channel_values", {})
            ckpt_values = {}
            if title := channel_values.get("title"):
                ckpt_values["title"] = title

            thread_resp = ThreadResponse(
                thread_id=thread_id,
                status=_derive_thread_status(checkpoint_tuple),
                created_at=_to_iso(ckpt_meta.get("created_at")),
                updated_at=_to_iso(ckpt_meta.get("updated_at", ckpt_meta.get("created_at"))),
                metadata=user_meta,
                values=ckpt_values,
            )
            merged[thread_id] = thread_resp

            # Lazy migration — write to Store so the next search finds it there
            if store is not None:
                try:
                    await _store_upsert(store, thread_id, metadata=user_meta, values=ckpt_values or None)
                except Exception:
                    logger.debug("Failed to migrate thread %s to store (non-fatal)", thread_id)
    except Exception:
        logger.exception("Checkpointer scan failed during thread search")
        # Don't raise — return whatever was collected from Store + partial scan

    # -----------------------------------------------------------------------
    # Phase 3: Filter → sort → paginate
    # -----------------------------------------------------------------------
    results = list(merged.values())

    # Filter out workflow child threads. They live on the same checkpointer
    # as user chat threads (so they survive restart and can be queried for
    # state) but are not user-facing — they appear as "Untitled" rows in
    # the chat sidebar otherwise. Source of truth: each parent thread
    # records its children in metadata.child_workflow_threads.
    workflow_child_ids: set[str] = set()
    for r in results:
        children = r.metadata.get("child_workflow_threads") if r.metadata else None
        if not isinstance(children, list):
            continue
        for entry in children:
            if isinstance(entry, dict):
                tid = entry.get("thread_id")
                if isinstance(tid, str) and tid:
                    workflow_child_ids.add(tid)
    if workflow_child_ids:
        results = [r for r in results if r.thread_id not in workflow_child_ids]

    if body.metadata:
        results = [r for r in results if all(r.metadata.get(k) == v for k, v in body.metadata.items())]

    if body.status:
        results = [r for r in results if r.status == body.status]

    results.sort(key=lambda r: r.updated_at, reverse=True)
    return results[body.offset : body.offset + body.limit]


@router.patch("/{thread_id}", response_model=ThreadResponse)
async def patch_thread(thread_id: str, body: ThreadPatchRequest, request: Request) -> ThreadResponse:
    """Merge metadata into a thread record."""
    store = get_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")

    record = await _store_get(store, thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    now = _iso_now()
    updated = dict(record)
    updated.setdefault("metadata", {}).update(body.metadata)
    updated["updated_at"] = now

    try:
        await _store_put(store, updated)
    except Exception:
        logger.exception("Failed to patch thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to update thread")

    return ThreadResponse(
        thread_id=thread_id,
        status=updated.get("status", "idle"),
        created_at=_to_iso(updated.get("created_at")),
        updated_at=now,
        metadata=updated.get("metadata", {}),
    )


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(thread_id: str, request: Request) -> ThreadResponse:
    """Get thread info.

    Reads metadata from the Store and derives the accurate execution
    status from the checkpointer.  Falls back to the checkpointer alone
    for threads that pre-date Store adoption (backward compat).
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)

    record: dict | None = None
    if store is not None:
        record = await _store_get(store, thread_id)

    # Derive accurate status from the checkpointer
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get checkpoint for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread")

    if record is None and checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # If the thread exists in the checkpointer but not the store (e.g. legacy
    # data), synthesize a minimal store record from the checkpoint metadata.
    if record is None and checkpoint_tuple is not None:
        ckpt_meta = getattr(checkpoint_tuple, "metadata", {}) or {}
        record = {
            "thread_id": thread_id,
            "status": "idle",
            "created_at": ckpt_meta.get("created_at", ""),
            "updated_at": ckpt_meta.get("updated_at", ckpt_meta.get("created_at", "")),
            "metadata": {k: v for k, v in ckpt_meta.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")},
        }

    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    status = _derive_thread_status(checkpoint_tuple) if checkpoint_tuple is not None else record.get("status", "idle")
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {} if checkpoint_tuple is not None else {}
    channel_values = checkpoint.get("channel_values", {})

    return ThreadResponse(
        thread_id=thread_id,
        status=status,
        created_at=_to_iso(record.get("created_at")),
        updated_at=_to_iso(record.get("updated_at")),
        metadata=record.get("metadata", {}),
        values=serialize_channel_values(channel_values),
    )


@router.get("/{thread_id}/children")
async def list_thread_children(
    thread_id: str,
    store: Any = Depends(get_store),
) -> dict:
    """Return the child workflow threads spawned by this chat thread.

    Each child entry has ``thread_id``, ``name``, and ``started_at``.
    """
    if store is None:
        return {"children": []}
    record = await _store_get(store, thread_id)
    metadata = (record or {}).get("metadata") or {}
    return {"children": list(metadata.get("child_workflow_threads") or [])}


@router.get("/{thread_id}/workflows/active")
async def list_active_workflows(thread_id: str, request: Request) -> dict:
    """Return non-terminal child workflows of *thread_id* with progress projection.

    Each entry: ``{thread_id, name, started_at, is_done, _error, progress}``
    where ``progress`` is the workflow's declared ``progress_fields`` projected
    from its current state. Children whose workflow name isn't registered or
    whose checkpoint can't be loaded are silently skipped.
    """
    store = get_store(request)
    checkpointer = get_checkpointer(request)
    if store is None:
        return {"active": []}

    record = await _store_get(store, thread_id)
    metadata = (record or {}).get("metadata") or {}
    children = list(metadata.get("child_workflow_threads") or [])
    if not children:
        return {"active": []}

    # Lazy import to avoid pulling workflow modules into router cold-start.
    from deerflow.workflows.tools import _get_registry

    try:
        registry = _get_registry()
    except RuntimeError:
        # Registry not initialized (e.g. tests that don't call set_registry).
        return {"active": []}

    out: list[dict] = []
    for child in children:
        child_tid = child.get("thread_id")
        wf_name = child.get("name")
        if not child_tid or not wf_name:
            continue
        if not registry.has(wf_name):
            continue
        spec = registry.get(wf_name)
        try:
            cp_tuple = await checkpointer.aget_tuple(
                {"configurable": {"thread_id": child_tid, "checkpoint_ns": ""}},
            )
        except Exception:
            logger.warning("active-workflows: failed to load checkpoint for %s", child_tid, exc_info=True)
            continue
        if cp_tuple is None:
            continue
        values = (cp_tuple.checkpoint or {}).get("channel_values", {}) or {}
        if values.get(spec.done_field):
            continue  # terminal — not active
        progress = {f: values[f] for f in spec.progress_fields if f in values}
        out.append({
            "thread_id": child_tid,
            "name": wf_name,
            "started_at": child.get("started_at"),
            "is_done": False,
            "_error": values.get("_error"),
            "progress": progress,
        })

    return {"active": out}


@router.post("/{thread_id}/workflows/{child_id}/cancel")
async def cancel_active_workflow(
    thread_id: str,
    child_id: str,
    request: Request,
) -> dict:
    """User-initiated cancel for a child workflow.

    Mirrors the ``cancel_workflow`` LLM tool's logic but called over HTTP from
    the frontend widget — does not go through LLM thinking.

    Returns ``{ok: bool, reason?: str}``. Does not 404 on unknown child to
    keep semantics consistent with cancel_workflow tool (returns informative
    text rather than HTTP error).
    """
    # Lazy import — same reason as in list_active_workflows.
    from deerflow.workflows.tools import _BG_TASKS, _THREAD_TO_WORKFLOW

    if child_id not in _THREAD_TO_WORKFLOW:
        return {"ok": False, "reason": "not a registered workflow thread"}
    task = _BG_TASKS.get(child_id)
    if task is None or task.done():
        return {"ok": False, "reason": "workflow already finished"}
    task.cancel()
    return {"ok": True}


@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
async def get_thread_state(thread_id: str, request: Request) -> ThreadStateResponse:
    """Get the latest state snapshot for a thread.

    Channel values are serialized to ensure LangChain message objects
    are converted to JSON-safe dicts.
    """
    checkpointer = get_checkpointer(request)

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get state for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
    checkpoint_id = None
    ckpt_config = getattr(checkpoint_tuple, "config", {})
    if ckpt_config:
        checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id")

    channel_values = checkpoint.get("channel_values", {})

    parent_config = getattr(checkpoint_tuple, "parent_config", None)
    parent_checkpoint_id = None
    if parent_config:
        parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")

    tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
    next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]
    tasks = [{"id": getattr(t, "id", ""), "name": getattr(t, "name", "")} for t in tasks_raw]

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=next_tasks,
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": str(metadata.get("created_at", ""))},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
        tasks=tasks,
    )


@router.post("/{thread_id}/state", response_model=ThreadStateResponse)
async def update_thread_state(thread_id: str, body: ThreadStateUpdateRequest, request: Request) -> ThreadStateResponse:
    """Update thread state (e.g. for human-in-the-loop resume or title rename).

    Writes a new checkpoint that merges *body.values* into the latest
    channel values, then syncs any updated ``title`` field back to the Store
    so that ``/threads/search`` reflects the change immediately.
    """
    checkpointer = get_checkpointer(request)
    store = get_store(request)

    # checkpoint_ns must be present in the config for aput — default to ""
    # (the root graph namespace).  checkpoint_id is optional; omitting it
    # fetches the latest checkpoint for the thread.
    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    if body.checkpoint_id:
        read_config["configurable"]["checkpoint_id"] = body.checkpoint_id

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception:
        logger.exception("Failed to get state for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # Work on mutable copies so we don't accidentally mutate cached objects.
    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))

    if body.values:
        channel_values.update(body.values)

    checkpoint["channel_values"] = channel_values
    metadata["updated_at"] = _iso_now()

    if body.as_node:
        metadata["source"] = "update"
        metadata["step"] = metadata.get("step", 0) + 1
        metadata["writes"] = {body.as_node: body.values}

    # aput requires checkpoint_ns in the config — use the same config used for the
    # read (which always includes checkpoint_ns="").  Do NOT include checkpoint_id
    # so that aput generates a fresh checkpoint ID for the new snapshot.
    write_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        new_config = await checkpointer.aput(write_config, checkpoint, metadata, {})
    except Exception:
        logger.exception("Failed to update state for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    new_checkpoint_id: str | None = None
    if isinstance(new_config, dict):
        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id")

    # Sync title changes to the Store so /threads/search reflects them immediately.
    if store is not None and body.values and "title" in body.values:
        try:
            await _store_upsert(store, thread_id, values={"title": body.values["title"]})
        except Exception:
            logger.debug("Failed to sync title to store for thread %s (non-fatal)", thread_id)

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=[],
        metadata=metadata,
        checkpoint_id=new_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
    )


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
async def get_thread_history(thread_id: str, body: ThreadHistoryRequest, request: Request) -> list[HistoryEntry]:
    """Get checkpoint history for a thread."""
    checkpointer = get_checkpointer(request)

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if body.before:
        config["configurable"]["checkpoint_id"] = body.before

    entries: list[HistoryEntry] = []
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=body.limit):
            ckpt_config = getattr(checkpoint_tuple, "config", {})
            parent_config = getattr(checkpoint_tuple, "parent_config", None)
            metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}

            checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id", "")
            parent_id = None
            if parent_config:
                parent_id = parent_config.get("configurable", {}).get("checkpoint_id")

            channel_values = checkpoint.get("channel_values", {})

            # Derive next tasks
            tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
            next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]

            entries.append(
                HistoryEntry(
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    metadata=metadata,
                    values=serialize_channel_values(channel_values),
                    created_at=str(metadata.get("created_at", "")),
                    next=next_tasks,
                )
            )
    except Exception:
        logger.exception("Failed to get history for thread %s", thread_id)
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    return entries
