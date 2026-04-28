# Child Workflow Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the frontend "Active workflows" panel to the workspace sidebar (with cross-thread unread red dot) and the two backend endpoints + metadata stamping it requires.

**Architecture:** Backend gets two new HTTP endpoints (`GET /api/threads/{tid}/workflows/active`, `POST /api/threads/{tid}/workflows/{cid}/cancel`) and stamps `recent_workflow_finish_at` into parent thread metadata at terminal events. Frontend polls the active endpoint per chat thread (2s), renders a sidebar bottom panel with progress bars + cancel buttons, and shows a red dot on chat-list items whose `recent_workflow_finish_at > lastViewedAt[threadId]` (in-memory zustand store, session-only).

**Tech Stack:** Backend = FastAPI + langgraph + existing `WorkflowRegistry` / `_THREAD_TO_WORKFLOW` / `_BG_TASKS` singletons. Frontend = React Query (already present, used by `useThreads`), zustand (project pattern), shadcn/ui sidebar primitives, existing `useThread` context.

**Spec:** [`docs/superpowers/specs/2026-04-28-child-workflow-widget-design.md`](../specs/2026-04-28-child-workflow-widget-design.md). **Phase 1 baseline:** `docs/superpowers/STATUS-2026-04-28.md`.

**Conventions verified in this repo:**
- All new HTTP routes live on the `router` in `backend/app/gateway/routers/threads.py` mounted at `/api/threads`.
- All store reads/writes go through `_store_get` / `_store_put` / `_store_upsert` in that file (never direct keys).
- All workflow background side-effects go through `deerflow.runtime.store_singleton.get_default_store()` (see `tools.py:252`).
- Frontend HTTP code lives under `frontend/src/core/<domain>/{api,hooks,types}.ts`; components under `frontend/src/components/workspace/<feature>/`.
- Frontend uses **react-query** (`@tanstack/react-query`), not SWR.
- Frontend uses **zustand** for client state (`core/settings/store.ts` is the reference pattern).
- Tests: backend uses `pytest` + `pytest-asyncio`; frontend uses `vitest` (`pnpm test`).

---

## File Structure

### Backend new

```
backend/packages/harness/deerflow/workflows/finish_stamp.py
  Helper that writes recent_workflow_finish_at into parent thread store metadata.
backend/tests/test_workflows_finish_stamp.py
backend/tests/test_workflows_active_endpoint.py
backend/tests/test_workflows_cancel_endpoint.py
```

### Backend modify

```
backend/packages/harness/deerflow/workflows/background.py
  Call stamp_parent_finish() after _wait_for_parent_idle() in success / failure / cancel paths.
backend/app/gateway/routers/threads.py
  +GET /{thread_id}/workflows/active
  +POST /{thread_id}/workflows/{child_id}/cancel
```

### Frontend new

```
frontend/src/core/workflows/api.ts
frontend/src/core/workflows/hooks.ts
frontend/src/core/workflows/types.ts
frontend/src/core/workflows/index.ts

frontend/src/core/threads/use-thread-viewed.ts
  Zustand store: lastViewedAt: Record<threadId, epochMs>; markViewed(tid).

frontend/src/components/workspace/active-workflows-panel/index.tsx
frontend/src/components/workspace/active-workflows-panel/workflow-row.tsx
frontend/src/components/workspace/active-workflows-panel/progress-line.tsx

frontend/src/core/workflows/__tests__/use-active-workflows.test.ts
frontend/src/core/threads/__tests__/use-thread-viewed.test.ts
frontend/src/components/workspace/active-workflows-panel/__tests__/progress-line.test.tsx
```

### Frontend modify

```
frontend/src/components/workspace/workspace-sidebar.tsx
  Mount <ActiveWorkflowsPanel /> in <SidebarContent>, after <RecentChatList />.
frontend/src/components/workspace/recent-chat-list.tsx
  Render red-dot when thread.metadata.recent_workflow_finish_at > lastViewedAt[tid].
  Call markViewed(tid) on link click.
```

---

## Batch A — Backend

### Task A1: `stamp_parent_finish()` helper

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/finish_stamp.py`
- Test: `backend/tests/test_workflows_finish_stamp.py`

Mirrors `_record_child_workflow_thread` in `tools.py` (best-effort, swallows errors, uses default store). Writes `metadata.recent_workflow_finish_at = max(existing, now_iso)` on the **parent** thread record. Single source of truth so `background.py` doesn't need to duplicate the upsert logic.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflows_finish_stamp.py
"""Tests for the recent_workflow_finish_at parent-metadata stamper."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore


@pytest.mark.asyncio
async def test_stamp_writes_iso_timestamp(monkeypatch):
    from deerflow.workflows.finish_stamp import stamp_parent_finish
    import deerflow.runtime.store_singleton as ss

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)

    parent = "p-1"
    # Pre-create the parent record (mirrors how chat threads exist).
    from app.gateway.routers.threads import _store_upsert
    await _store_upsert(store, parent, metadata={})

    await stamp_parent_finish(parent)

    rec = (await store.aget(("threads",), parent)).value
    ts = rec["metadata"]["recent_workflow_finish_at"]
    assert ts.endswith("+00:00") or ts.endswith("Z")


@pytest.mark.asyncio
async def test_stamp_is_monotonic(monkeypatch):
    """Two stamps in a row must leave the larger timestamp in metadata."""
    from deerflow.workflows.finish_stamp import stamp_parent_finish
    import deerflow.runtime.store_singleton as ss

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)

    parent = "p-2"
    from app.gateway.routers.threads import _store_upsert
    await _store_upsert(store, parent, metadata={
        "recent_workflow_finish_at": "2099-01-01T00:00:00+00:00",  # far future
    })

    await stamp_parent_finish(parent)

    rec = (await store.aget(("threads",), parent)).value
    # The pre-existing far-future stamp must survive (now() is smaller).
    assert rec["metadata"]["recent_workflow_finish_at"] == "2099-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_stamp_swallows_missing_store(monkeypatch):
    """No store registered = no-op, no exception."""
    from deerflow.workflows.finish_stamp import stamp_parent_finish
    import deerflow.runtime.store_singleton as ss

    monkeypatch.setattr(ss, "get_default_store", lambda: None)
    await stamp_parent_finish("anything")  # must not raise


@pytest.mark.asyncio
async def test_stamp_creates_record_if_missing(monkeypatch):
    """If parent has no store record yet, stamp creates one with the timestamp."""
    from deerflow.workflows.finish_stamp import stamp_parent_finish
    import deerflow.runtime.store_singleton as ss

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)

    await stamp_parent_finish("brand-new")

    rec = (await store.aget(("threads",), "brand-new"))
    assert rec is not None
    assert "recent_workflow_finish_at" in rec.value["metadata"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_workflows_finish_stamp.py -v`
Expected: FAIL with `ModuleNotFoundError: deerflow.workflows.finish_stamp`

- [ ] **Step 3: Write the implementation**

```python
# backend/packages/harness/deerflow/workflows/finish_stamp.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_workflows_finish_stamp.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/finish_stamp.py backend/tests/test_workflows_finish_stamp.py
git commit -m "feat(workflows): stamp_parent_finish helper for recent_workflow_finish_at"
```

---

### Task A2: Wire `stamp_parent_finish` into `background.py`

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/background.py`
- Test: `backend/tests/test_workflows_background.py` (extend existing)

Three call sites: success path (after the existing `emit_to_parent_thread`), failure path (after the failure emit), cancel path (after the cancel emit). Each call sits **after** `_wait_for_parent_idle` and **after** the emit; if emit raises, the existing best-effort try/except already guards. The stamp itself is best-effort too, so we don't add new try/except — `stamp_parent_finish` swallows internally.

- [ ] **Step 1: Add a failing test for the success path**

Add this test to the existing `backend/tests/test_workflows_background.py` (don't create a new file). Read the file first to copy its imports & fixtures.

```python
@pytest.mark.asyncio
async def test_run_workflow_background_stamps_finish_on_success(monkeypatch, tmp_path):
    """Successful workflow ⇒ recent_workflow_finish_at written on parent."""
    from langgraph.store.memory import InMemoryStore
    from app.gateway.routers.threads import _store_upsert
    import deerflow.runtime.store_singleton as ss

    store = InMemoryStore()
    monkeypatch.setattr(ss, "get_default_store", lambda: store)
    parent_tid = "p-success"
    await _store_upsert(store, parent_tid, metadata={})

    # Use the existing demo-flow fixture that the file already wires.
    # (Look in test_workflows_background.py for `_make_spec` or similar
    # — copy that helper.) Then run the bg task end-to-end.
    spec = _make_demo_flow_spec()  # from existing helpers in this file
    cp = _make_checkpointer(tmp_path)  # from existing helpers
    child_tid = "c-success"

    from deerflow.workflows.background import run_workflow_background
    await run_workflow_background(
        spec=spec, params={"task_name": "x"},
        child_thread_id=child_tid, parent_thread_id=parent_tid,
        checkpointer=cp,
    )

    rec = (await store.aget(("threads",), parent_tid)).value
    assert "recent_workflow_finish_at" in rec["metadata"]
```

If existing helpers like `_make_demo_flow_spec` / `_make_checkpointer` don't exist with those exact names, **read the file** and adapt to whatever fixture pattern it uses. Add similar tests for the failure path (a spec whose graph raises) and cancel path (a spec whose graph awaits `asyncio.sleep` then is `task.cancel()`'d). If the existing tests have these scenarios, just append `assert` lines for the stamp.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_workflows_background.py -v -k stamp`
Expected: FAIL — KeyError on `recent_workflow_finish_at`

- [ ] **Step 3: Wire `stamp_parent_finish` into the three terminal paths**

Edit `backend/packages/harness/deerflow/workflows/background.py`. Add this import at the top with the other workflow imports:

```python
from deerflow.workflows.finish_stamp import stamp_parent_finish
```

In `run_workflow_background`, add a `await stamp_parent_finish(parent_thread_id)` call **immediately after** each `_wait_for_parent_idle(parent_thread_id)` call — there are three:
1. After cancel-path `_wait_for_parent_idle` (current line ~118)
2. After failure-path `_wait_for_parent_idle` (current line ~140)
3. After success-path `_wait_for_parent_idle` inside the `if report:` branch (current line ~156)

Place the stamp call **before** the `try: emit_to_parent_thread(...)` block so that even if emit fails, the stamp landed (the dot is independent UX from the emitted message).

For each location, the structure becomes:
```python
await _wait_for_parent_idle(parent_thread_id)
await stamp_parent_finish(parent_thread_id)
try:
    await emit_to_parent_thread(...)
except Exception:
    logger.exception(...)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_workflows_background.py -v`
Expected: all pass (including the new `_stamps_finish_on_*` tests)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/background.py backend/tests/test_workflows_background.py
git commit -m "feat(workflows): stamp recent_workflow_finish_at at terminal events"
```

---

### Task A3: `GET /api/threads/{tid}/workflows/active` endpoint

**Files:**
- Modify: `backend/app/gateway/routers/threads.py` (add new route, no other changes)
- Test: `backend/tests/test_workflows_active_endpoint.py`

Returns active (i.e. `is_done == False`) child workflows for a given parent thread. Iterates `metadata.child_workflow_threads`, fetches each child's state via the shared checkpointer, projects `progress_fields`. Children that fail to load are silently skipped.

Reuses existing helpers `_store_get`, `get_checkpointer(request)`, `serialize_channel_values`. We do **not** consult `_THREAD_TO_WORKFLOW` here because the source of truth across gateway restarts is the parent thread's `child_workflow_threads` metadata + each child's checkpointed state.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflows_active_endpoint.py
"""Tests for GET /api/threads/{tid}/workflows/active."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


def _make_request(store, checkpointer):
    """Mimic FastAPI's Request for the helpers that read app.state."""
    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = checkpointer
    return req


async def _seed_child(checkpointer, child_tid: str, values: dict) -> None:
    """Write a single checkpoint with given channel_values for a child thread."""
    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict

    class S(TypedDict, total=False):
        is_done: bool
        current_round: int
        max_rounds: int
        report: str

    g = StateGraph(S)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    graph = g.compile(checkpointer=checkpointer)
    await graph.aupdate_state(
        config={"configurable": {"thread_id": child_tid}},
        values=values,
    )


@pytest.mark.asyncio
async def test_active_endpoint_returns_only_running(monkeypatch):
    """Of two children, one done and one running, only the running one comes back."""
    from app.gateway.routers.threads import (
        _store_upsert, list_active_workflows,
    )

    store = InMemoryStore()
    cp = InMemorySaver()
    parent = "parent-A"

    await _store_upsert(store, parent, metadata={
        "child_workflow_threads": [
            {"thread_id": "c-running", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
            {"thread_id": "c-done", "name": "demo-flow", "started_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    await _seed_child(cp, "c-running", {"is_done": False, "current_round": 3, "max_rounds": 10})
    await _seed_child(cp, "c-done", {"is_done": True, "current_round": 10, "max_rounds": 10, "report": "ok"})

    # Fake registry so the endpoint can look up progress_fields.
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class P(BaseModel): ...
    spec = WorkflowSpec(
        name="demo-flow", description="", factory=lambda **_: None,
        input_schema=P, done_field="is_done", report_field="report",
        progress_fields=["current_round", "max_rounds"],
    )
    fake_reg = WorkflowRegistry([spec], failures=[])
    import deerflow.workflows.tools as wftools
    monkeypatch.setattr(wftools, "_REGISTRY", fake_reg)

    req = _make_request(store, cp)
    result = await list_active_workflows(parent, request=req)

    assert len(result["active"]) == 1
    item = result["active"][0]
    assert item["thread_id"] == "c-running"
    assert item["name"] == "demo-flow"
    assert item["is_done"] is False
    assert item["progress"] == {"current_round": 3, "max_rounds": 10}


@pytest.mark.asyncio
async def test_active_endpoint_handles_unknown_workflow_name(monkeypatch):
    """Child whose workflow name isn't registered is skipped, doesn't crash."""
    from app.gateway.routers.threads import _store_upsert, list_active_workflows
    from deerflow.workflows.registry import WorkflowRegistry
    import deerflow.workflows.tools as wftools

    store = InMemoryStore()
    cp = InMemorySaver()
    await _store_upsert(store, "p", metadata={
        "child_workflow_threads": [
            {"thread_id": "c", "name": "ghost-workflow", "started_at": "2026-01-01T00:00:00+00:00"},
        ],
    })
    monkeypatch.setattr(wftools, "_REGISTRY", WorkflowRegistry([], failures=[]))

    req = _make_request(store, cp)
    result = await list_active_workflows("p", request=req)
    assert result == {"active": []}


@pytest.mark.asyncio
async def test_active_endpoint_no_metadata_returns_empty(monkeypatch):
    from app.gateway.routers.threads import list_active_workflows

    req = _make_request(InMemoryStore(), InMemorySaver())
    result = await list_active_workflows("missing", request=req)
    assert result == {"active": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_workflows_active_endpoint.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_active_workflows'`

- [ ] **Step 3: Add the endpoint**

Open `backend/app/gateway/routers/threads.py`. Add this route **after** the existing `list_thread_children` function (around line 553, right after the `/children` route).

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_workflows_active_endpoint.py -v`
Expected: 3 passed

Also run lint:
```bash
cd backend && uv run ruff check app/gateway/routers/threads.py
```
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/threads.py backend/tests/test_workflows_active_endpoint.py
git commit -m "feat(workflows): GET /threads/{tid}/workflows/active endpoint"
```

---

### Task A4: `POST /api/threads/{tid}/workflows/{cid}/cancel` endpoint

**Files:**
- Modify: `backend/app/gateway/routers/threads.py`
- Test: `backend/tests/test_workflows_cancel_endpoint.py`

User-initiated cancel must not go through LLM thinking. Reuses the same in-process `_BG_TASKS` registry that `cancel_workflow` LLM tool uses, so behavior matches exactly.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_workflows_cancel_endpoint.py
"""Tests for POST /api/threads/{tid}/workflows/{cid}/cancel."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_cancel_endpoint_cancels_known_child(monkeypatch):
    from app.gateway.routers.threads import cancel_active_workflow
    import deerflow.workflows.tools as wftools

    parent_tid = "p"
    child_tid = "c"

    async def _runner():
        await asyncio.sleep(60)

    task = asyncio.create_task(_runner())
    monkeypatch.setattr(wftools, "_BG_TASKS", {child_tid: task}, raising=False)
    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {child_tid: "demo-flow"}, raising=False)

    req = MagicMock()
    result = await cancel_active_workflow(parent_tid, child_tid, request=req)

    assert result == {"ok": True}
    # Yield once so the cancellation propagates.
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_cancel_endpoint_unknown_child(monkeypatch):
    from app.gateway.routers.threads import cancel_active_workflow
    import deerflow.workflows.tools as wftools

    monkeypatch.setattr(wftools, "_BG_TASKS", {}, raising=False)
    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {}, raising=False)

    req = MagicMock()
    result = await cancel_active_workflow("p", "ghost", request=req)
    assert result == {"ok": False, "reason": "not a registered workflow thread"}


@pytest.mark.asyncio
async def test_cancel_endpoint_already_done(monkeypatch):
    from app.gateway.routers.threads import cancel_active_workflow
    import deerflow.workflows.tools as wftools

    async def _done():
        return None
    task = asyncio.create_task(_done())
    await task

    monkeypatch.setattr(wftools, "_BG_TASKS", {"c": task}, raising=False)
    monkeypatch.setattr(wftools, "_THREAD_TO_WORKFLOW", {"c": "demo-flow"}, raising=False)

    req = MagicMock()
    result = await cancel_active_workflow("p", "c", request=req)
    assert result == {"ok": False, "reason": "workflow already finished"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_workflows_cancel_endpoint.py -v`
Expected: FAIL with `ImportError: cannot import name 'cancel_active_workflow'`

- [ ] **Step 3: Add the endpoint**

In `backend/app/gateway/routers/threads.py`, immediately after `list_active_workflows` (added in Task A3), add:

```python
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
```

Note: `thread_id` (parent) is in the path for symmetry/future use; we don't currently validate it against the child relationship. The `_THREAD_TO_WORKFLOW` registry already prevents cancelling chat threads. Don't add validation we don't need.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_workflows_cancel_endpoint.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/threads.py backend/tests/test_workflows_cancel_endpoint.py
git commit -m "feat(workflows): POST /threads/{tid}/workflows/{cid}/cancel endpoint"
```

---

### Task A5: Backend integration check

**Files:** None modified. Verification only.

- [ ] **Step 1: Full backend test suite + lint**

```bash
cd backend && uv run ruff check . && uv run pytest tests/
```
Expected: lint clean, all tests pass (2208 + ~10 new = ~2218 passed, 3 skipped).

- [ ] **Step 2: Manual smoke (gateway already running per `make dev-pro`)**

```bash
# Replace 7aec6e32... with a real parent thread id from your dev gateway.
curl -s http://localhost:2026/api/threads/7aec6e32-31bb-4d67-b74d-aeae9d0a77ca/workflows/active | python -m json.tool
```
Expected: `{"active": []}` if no children, or a list of running children with `progress` projection.

If you have time and a running workflow, also smoke the cancel endpoint:
```bash
curl -s -X POST http://localhost:2026/api/threads/<parent>/workflows/<child>/cancel
# Expected: {"ok": true} or informative reason
```

- [ ] **Step 3: Commit nothing (verification only).**

---

## Batch B — Frontend

### Task B1: Workflow types + API client

**Files:**
- Create: `frontend/src/core/workflows/types.ts`
- Create: `frontend/src/core/workflows/api.ts`
- Create: `frontend/src/core/workflows/index.ts`

- [ ] **Step 1: Write types**

```typescript
// frontend/src/core/workflows/types.ts
export interface WorkflowProgressItem {
  thread_id: string;
  name: string;
  started_at: string | null;
  is_done: boolean;
  _error: string | null;
  progress: Record<string, unknown>;
}

export interface ActiveWorkflowsResponse {
  active: WorkflowProgressItem[];
}

export interface CancelWorkflowResponse {
  ok: boolean;
  reason?: string;
}
```

- [ ] **Step 2: Write API client**

```typescript
// frontend/src/core/workflows/api.ts
import { getBackendBaseURL } from "@/core/config";

import type { ActiveWorkflowsResponse, CancelWorkflowResponse } from "./types";

export async function fetchActiveWorkflows(
  threadId: string,
  signal?: AbortSignal,
): Promise<ActiveWorkflowsResponse> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/workflows/active`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`fetchActiveWorkflows: HTTP ${response.status}`);
  }
  return (await response.json()) as ActiveWorkflowsResponse;
}

export async function cancelActiveWorkflow(
  parentThreadId: string,
  childThreadId: string,
): Promise<CancelWorkflowResponse> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(parentThreadId)}/workflows/${encodeURIComponent(childThreadId)}/cancel`;
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) {
    throw new Error(`cancelActiveWorkflow: HTTP ${response.status}`);
  }
  return (await response.json()) as CancelWorkflowResponse;
}
```

- [ ] **Step 3: Write index re-exports**

```typescript
// frontend/src/core/workflows/index.ts
export * from "./types";
export * from "./api";
export * from "./hooks";
```

- [ ] **Step 4: Verify it compiles**

Run: `cd frontend && pnpm typecheck`
Expected: no new errors. (`./hooks` doesn't exist yet — typecheck will fail on the index re-export. **Skip Step 5 commit until Task B2.**)

- [ ] **Step 5: (Skip — combined with B2)**

---

### Task B2: `useActiveWorkflows` hook (react-query polling)

**Files:**
- Create: `frontend/src/core/workflows/hooks.ts`
- Test: `frontend/src/core/workflows/__tests__/use-active-workflows.test.ts`

- [ ] **Step 1: Write the failing test**

Look at `frontend/src/core/threads/hooks.ts` for the project's react-query patterns (e.g. `useThreads`). The hook test follows the same fixture style as existing frontend tests; if no comparable test exists, use this minimal vitest + `@tanstack/react-query` pattern:

```typescript
// frontend/src/core/workflows/__tests__/use-active-workflows.test.ts
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { useActiveWorkflows } from "../hooks";

const fetchMock = vi.fn();
vi.mock("../api", () => ({
  fetchActiveWorkflows: (...args: unknown[]) => fetchMock(...args),
  cancelActiveWorkflow: vi.fn(),
}));

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useActiveWorkflows", () => {
  let client: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });
  afterEach(() => client.clear());

  it("returns empty array when threadId is null", async () => {
    const { result } = renderHook(
      () => useActiveWorkflows(null),
      { wrapper: wrapper(client) },
    );
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.data).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("calls fetchActiveWorkflows with threadId and returns active list", async () => {
    fetchMock.mockResolvedValue({
      active: [{
        thread_id: "c1", name: "demo-flow", started_at: "2026-01-01T00:00:00+00:00",
        is_done: false, _error: null, progress: { current_round: 3, max_rounds: 10 },
      }],
    });
    const { result } = renderHook(
      () => useActiveWorkflows("p1"),
      { wrapper: wrapper(client) },
    );
    await waitFor(() => expect(result.current.data?.length).toBe(1));
    expect(fetchMock).toHaveBeenCalledWith("p1", expect.any(AbortSignal));
    expect(result.current.data?.[0]?.thread_id).toBe("c1");
  });
});
```

If frontend test infrastructure differs (e.g. project uses a different testing-library setup), inspect one existing test like `frontend/src/core/**/__tests__/*.test.ts` and conform. If **no** frontend tests exist yet, add a minimal `vitest.config.ts` only if the project lacks one — otherwise rely on existing config.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test src/core/workflows`
Expected: FAIL — `useActiveWorkflows` not found.

- [ ] **Step 3: Implement hook**

```typescript
// frontend/src/core/workflows/hooks.ts
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";

import { cancelActiveWorkflow, fetchActiveWorkflows } from "./api";
import type { WorkflowProgressItem } from "./types";

const POLL_INTERVAL_MS = 2_000;

export function useActiveWorkflows(threadId: string | null) {
  return useQuery<WorkflowProgressItem[]>({
    queryKey: ["workflows", "active", threadId],
    queryFn: async ({ signal }) => {
      if (!threadId) return [];
      const res = await fetchActiveWorkflows(threadId, signal);
      return res.active;
    },
    enabled: Boolean(threadId),
    refetchInterval: threadId ? POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
    initialData: threadId ? undefined : [],
  });
}

export function useCancelActiveWorkflow(parentThreadId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (childThreadId: string) => {
      if (!parentThreadId) throw new Error("parentThreadId required");
      return await cancelActiveWorkflow(parentThreadId, childThreadId);
    },
    onSuccess: () => {
      // The bg task may take a beat to roll the child to terminal state and
      // stamp the parent. Aggressively re-poll so the row disappears fast.
      void queryClient.invalidateQueries({
        queryKey: ["workflows", "active", parentThreadId],
      });
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test src/core/workflows && pnpm typecheck
```
Expected: tests green, typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/workflows/
git commit -m "feat(frontend): useActiveWorkflows + useCancelActiveWorkflow hooks"
```

---

### Task B3: `useThreadViewed` zustand store

**Files:**
- Create: `frontend/src/core/threads/use-thread-viewed.ts`
- Test: `frontend/src/core/threads/__tests__/use-thread-viewed.test.ts`

In-memory only. **No** persistence — session-only semantics per spec §6 / Q7-C.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/core/threads/__tests__/use-thread-viewed.test.ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasUnreadFinish, useThreadViewed } from "../use-thread-viewed";

describe("useThreadViewed", () => {
  it("markViewed records timestamp", () => {
    const { result } = renderHook(() => useThreadViewed());
    act(() => result.current.markViewed("t1"));
    expect(result.current.lastViewedAt["t1"]).toBeGreaterThan(0);
  });
});

describe("hasUnreadFinish", () => {
  it("returns false when no finish timestamp", () => {
    expect(hasUnreadFinish(undefined, undefined)).toBe(false);
    expect(hasUnreadFinish(null, undefined)).toBe(false);
  });
  it("returns true when finish > lastViewed", () => {
    const finish = "2026-04-28T12:00:00+00:00";
    const lastViewed = Date.parse("2026-04-28T11:59:00+00:00");
    expect(hasUnreadFinish(finish, lastViewed)).toBe(true);
  });
  it("returns false when finish <= lastViewed", () => {
    const finish = "2026-04-28T12:00:00+00:00";
    const lastViewed = Date.parse("2026-04-28T12:00:01+00:00");
    expect(hasUnreadFinish(finish, lastViewed)).toBe(false);
  });
  it("returns true when never viewed but workflow finished", () => {
    expect(hasUnreadFinish("2026-04-28T12:00:00+00:00", undefined)).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm test src/core/threads/__tests__/use-thread-viewed
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the store**

```typescript
// frontend/src/core/threads/use-thread-viewed.ts
import { create } from "zustand";

interface ThreadViewedState {
  lastViewedAt: Record<string, number>;
  markViewed: (threadId: string) => void;
}

export const useThreadViewed = create<ThreadViewedState>((set) => ({
  lastViewedAt: {},
  markViewed: (threadId) =>
    set((s) => ({
      lastViewedAt: { ...s.lastViewedAt, [threadId]: Date.now() },
    })),
}));

/**
 * Pure helper for determining whether a thread should display the
 * "unread workflow finish" red dot.
 *
 * - finishAt = thread.metadata.recent_workflow_finish_at (ISO or null/undef)
 * - lastViewed = epoch ms last time user navigated into this thread
 *   (undefined = never viewed in this session)
 */
export function hasUnreadFinish(
  finishAt: string | null | undefined,
  lastViewed: number | undefined,
): boolean {
  if (!finishAt) return false;
  const finishMs = Date.parse(finishAt);
  if (Number.isNaN(finishMs)) return false;
  if (lastViewed === undefined) return true;
  return finishMs > lastViewed;
}
```

If `zustand` is not yet a dependency, check via `grep -F '"zustand"' frontend/package.json`. If absent, **stop** and add it: `cd frontend && pnpm add zustand`. (Note: project should already have it — `core/settings/store.ts` reportedly uses it.) If it's not present, install it before continuing.

- [ ] **Step 4: Run tests + typecheck**

```bash
cd frontend && pnpm test src/core/threads/__tests__/use-thread-viewed && pnpm typecheck
```
Expected: green, clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/threads/use-thread-viewed.ts frontend/src/core/threads/__tests__/use-thread-viewed.test.ts
git commit -m "feat(frontend): useThreadViewed zustand store + hasUnreadFinish helper"
```

---

### Task B4: `ProgressLine` component

**Files:**
- Create: `frontend/src/components/workspace/active-workflows-panel/progress-line.tsx`
- Test: `frontend/src/components/workspace/active-workflows-panel/__tests__/progress-line.test.tsx`

Renders the progress portion of a row. Three fallback levels: bar / number / "running".

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/components/workspace/active-workflows-panel/__tests__/progress-line.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressLine } from "../progress-line";

describe("ProgressLine", () => {
  it("renders 'round X/Y' with bar when both fields present", () => {
    render(<ProgressLine progress={{ current_round: 3, max_rounds: 10 }} />);
    expect(screen.getByText(/round 3\/10/)).toBeTruthy();
  });
  it("renders 'round N' without bar when only current_round present", () => {
    render(<ProgressLine progress={{ current_round: 5 }} />);
    expect(screen.getByText(/round 5/)).toBeTruthy();
  });
  it("renders 'running' fallback when no recognized fields", () => {
    render(<ProgressLine progress={{}} />);
    expect(screen.getByText(/running/i)).toBeTruthy();
  });
  it("ignores wrong-typed values and falls back", () => {
    render(<ProgressLine progress={{ current_round: "abc" }} />);
    expect(screen.getByText(/running/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm test src/components/workspace/active-workflows-panel
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/components/workspace/active-workflows-panel/progress-line.tsx
"use client";

import { Progress } from "@/components/ui/progress";

interface Props {
  progress: Record<string, unknown>;
}

export function ProgressLine({ progress }: Props) {
  const cur = progress.current_round;
  const max = progress.max_rounds;
  if (typeof cur === "number" && typeof max === "number" && max > 0) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">
          round {cur}/{max}
        </span>
        <Progress value={(cur / max) * 100} className="h-1" />
      </div>
    );
  }
  if (typeof cur === "number") {
    return (
      <span className="text-muted-foreground text-xs">round {cur}</span>
    );
  }
  return (
    <span className="text-muted-foreground text-xs italic">running</span>
  );
}
```

`Progress` from shadcn/ui (`@/components/ui/progress`) — confirmed present in repo (`@radix-ui/react-progress` in package.json).

- [ ] **Step 4: Run tests + typecheck**

```bash
cd frontend && pnpm test src/components/workspace/active-workflows-panel && pnpm typecheck
```
Expected: green, clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/active-workflows-panel/progress-line.tsx frontend/src/components/workspace/active-workflows-panel/__tests__/
git commit -m "feat(frontend): ProgressLine component for workflow widget"
```

---

### Task B5: `WorkflowRow` and `ActiveWorkflowsPanel`

**Files:**
- Create: `frontend/src/components/workspace/active-workflows-panel/workflow-row.tsx`
- Create: `frontend/src/components/workspace/active-workflows-panel/index.tsx`

The panel reads the current thread id from URL params (`useParams`) — same pattern as `recent-chat-list.tsx:65`. Renders nothing when no current thread or no active workflows.

- [ ] **Step 1: Implement `WorkflowRow`**

```typescript
// frontend/src/components/workspace/active-workflows-panel/workflow-row.tsx
"use client";

import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SidebarMenuItem } from "@/components/ui/sidebar";
import type { WorkflowProgressItem } from "@/core/workflows";

import { ProgressLine } from "./progress-line";

interface Props {
  item: WorkflowProgressItem;
  onCancel: (childThreadId: string) => void;
  isCancelling?: boolean;
}

export function WorkflowRow({ item, onCancel, isCancelling }: Props) {
  return (
    <SidebarMenuItem className="flex flex-col gap-1 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm truncate">{item.name}</span>
        <Button
          size="icon"
          variant="ghost"
          className="h-5 w-5 shrink-0"
          aria-label={`Cancel ${item.name}`}
          disabled={isCancelling}
          onClick={() => onCancel(item.thread_id)}
        >
          <XIcon className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ProgressLine progress={item.progress} />
    </SidebarMenuItem>
  );
}
```

- [ ] **Step 2: Implement `ActiveWorkflowsPanel`**

```typescript
// frontend/src/components/workspace/active-workflows-panel/index.tsx
"use client";

import { useParams } from "next/navigation";
import { toast } from "sonner";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
} from "@/components/ui/sidebar";
import {
  useActiveWorkflows,
  useCancelActiveWorkflow,
} from "@/core/workflows";

import { WorkflowRow } from "./workflow-row";

export function ActiveWorkflowsPanel() {
  const { thread_id: threadId } = useParams<{ thread_id?: string }>();
  const currentThreadId = threadId ?? null;

  const { data = [] } = useActiveWorkflows(currentThreadId);
  const { mutate: cancel, isPending: isCancelling } =
    useCancelActiveWorkflow(currentThreadId);

  if (!currentThreadId || data.length === 0) return null;

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Active workflows ({data.length})</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {data.map((item) => (
            <WorkflowRow
              key={item.thread_id}
              item={item}
              isCancelling={isCancelling}
              onCancel={(child) =>
                cancel(child, {
                  onError: (e) =>
                    toast.error(`Cancel failed: ${(e as Error).message}`),
                })
              }
            />
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
```

- [ ] **Step 3: Run lint + typecheck**

```bash
cd frontend && pnpm lint src/components/workspace/active-workflows-panel/ && pnpm typecheck
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/workspace/active-workflows-panel/index.tsx frontend/src/components/workspace/active-workflows-panel/workflow-row.tsx
git commit -m "feat(frontend): ActiveWorkflowsPanel + WorkflowRow components"
```

---

### Task B6: Mount the panel in `WorkspaceSidebar`

**Files:**
- Modify: `frontend/src/components/workspace/workspace-sidebar.tsx`

- [ ] **Step 1: Edit the file**

Open `frontend/src/components/workspace/workspace-sidebar.tsx`. Add the import and mount the panel inside `<SidebarContent>`, after `<RecentChatList />`.

```typescript
import { ActiveWorkflowsPanel } from "./active-workflows-panel";
// ... existing imports
import { RecentChatList } from "./recent-chat-list";
// ... rest

// In the component body:
<SidebarContent>
  <WorkspaceNavChatList />
  {isSidebarOpen && <RecentChatList />}
  {isSidebarOpen && <ActiveWorkflowsPanel />}
</SidebarContent>
```

`isSidebarOpen` already gates `RecentChatList` (collapsible="icon" hides text in icon-only mode). Same gate applies to the workflow panel.

- [ ] **Step 2: Verify with manual smoke**

```bash
cd frontend && pnpm typecheck
```
Expected: clean.

Also start dev gateway + frontend (`make dev-pro` from root if not running) and:
1. Open a chat thread that has an active workflow (or start one with `start_workflow("demo-flow", {...})`)
2. Confirm the "Active workflows (N)" group appears at the bottom of the sidebar
3. Confirm progress updates within ~2s
4. Click `[×]` → row disappears, child workflow rolls to cancelled (verify in chat: `[workflow:demo-flow] cancelled by user` system message arrives)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/workspace/workspace-sidebar.tsx
git commit -m "feat(frontend): mount ActiveWorkflowsPanel in workspace sidebar"
```

---

### Task B7: Cross-thread red dot in `recent-chat-list.tsx`

**Files:**
- Modify: `frontend/src/components/workspace/recent-chat-list.tsx`

Render a red dot next to a thread row when `thread.metadata.recent_workflow_finish_at` is newer than the user's last visit (per `useThreadViewed`). Visit timestamp is updated when the link is clicked (or when `pathname` matches the thread's path on mount).

- [ ] **Step 1: Verify metadata comes through**

In `frontend/src/core/threads/types.ts` (or wherever `AgentThread` is defined), confirm `metadata: Record<string, unknown>` exists. (`useThreads` already requests `select: ["thread_id", "updated_at", "values", "metadata"]` per `hooks.ts:538` — so the field is already plumbed.) **No type change needed** unless `metadata` is currently typed too narrowly. If it is, widen its declaration to include `recent_workflow_finish_at?: string`.

- [ ] **Step 2: Edit the file**

Open `frontend/src/components/workspace/recent-chat-list.tsx`. At the top, add imports:

```typescript
import { useThreadViewed, hasUnreadFinish } from "@/core/threads/use-thread-viewed";
```

Inside `RecentChatList`, after the existing hooks (`useThreads` etc.), pull state + actions:

```typescript
const lastViewedAt = useThreadViewed((s) => s.lastViewedAt);
const markViewed = useThreadViewed((s) => s.markViewed);
```

Add an effect that marks the **currently active** thread as viewed whenever it changes:

```typescript
React.useEffect(() => {
  if (threadIdFromPath) markViewed(threadIdFromPath);
}, [threadIdFromPath, markViewed]);
```

(Add `import { useEffect } from "react"` if React isn't already imported as default. Existing file uses `import { useCallback, useState } from "react"` — extend to include `useEffect`.)

In the row render (look for `<Link ... href={pathOfThread(thread)}>`), wrap or append a red-dot element when `hasUnreadFinish(...)` returns true. Place it before/after the title text:

```tsx
{hasUnreadFinish(
  thread.metadata?.recent_workflow_finish_at as string | undefined,
  lastViewedAt[thread.thread_id],
) && (
  <span
    aria-label="Workflow finished — unread"
    className="ml-1 inline-block h-2 w-2 rounded-full bg-red-500 align-middle"
  />
)}
```

Place this inside the `<div>` that contains the `<Link>` so the dot sits next to the title.

Also call `markViewed(thread.thread_id)` on link click — but the existing `pathname`-based effect already handles route changes, so explicit click handler is **not** needed. Skip it to minimize edits.

- [ ] **Step 3: Test the helper logic again (re-runs Task B3 tests)**

```bash
cd frontend && pnpm test src/core/threads && pnpm typecheck
```
Expected: green, clean.

- [ ] **Step 4: Manual smoke**

1. Start a workflow on thread A
2. Switch to thread B (no workflow on B)
3. Wait for A's workflow to finish (or cancel it — cancel counts as terminal)
4. Confirm thread A's row in the sidebar shows a red dot
5. Click thread A → red dot disappears
6. Refresh page → red dot stays gone (because thread A is the active thread, `markViewed(threadIdFromPath)` runs in the mount effect)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/recent-chat-list.tsx
git commit -m "feat(frontend): red dot for unread workflow finish on chat list"
```

---

### Task B8: Cache invalidation polish

**Files:**
- Modify: `frontend/src/core/workflows/hooks.ts`

The `recent_workflow_finish_at` red dot relies on `useThreads` returning fresh metadata. `useThreads` invalidates on stream finish (already wired in `core/threads/hooks.ts:294-296` via `onFinish`). But a **child workflow** finishing doesn't trigger a stream event on the parent thread (only the emit does). To keep the red dot fresh without 10s polling on the chat list, we already proactively invalidate `["threads", "search"]` from `useCancelActiveWorkflow.onSuccess` (Task B2). Add the same invalidation when the active-workflows poll detects a workflow disappearing from the list.

- [ ] **Step 1: Edit `useActiveWorkflows`**

Open `frontend/src/core/workflows/hooks.ts`. Replace the `useActiveWorkflows` implementation with:

```typescript
import { useEffect, useRef } from "react";

// ... existing imports ...

export function useActiveWorkflows(threadId: string | null) {
  const queryClient = useQueryClient();
  const query = useQuery<WorkflowProgressItem[]>({
    queryKey: ["workflows", "active", threadId],
    queryFn: async ({ signal }) => {
      if (!threadId) return [];
      const res = await fetchActiveWorkflows(threadId, signal);
      return res.active;
    },
    enabled: Boolean(threadId),
    refetchInterval: threadId ? POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
    initialData: threadId ? undefined : [],
  });

  // When the active-workflow list shrinks (a workflow just finished),
  // invalidate the chat-list cache so its metadata.recent_workflow_finish_at
  // is refetched and the red-dot machinery can light up.
  const prevCountRef = useRef<number | null>(null);
  useEffect(() => {
    const len = query.data?.length ?? null;
    if (
      prevCountRef.current !== null &&
      len !== null &&
      len < prevCountRef.current
    ) {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    }
    prevCountRef.current = len;
  }, [query.data, queryClient]);

  return query;
}
```

(Move the existing `useQueryClient` import to the top imports if not already present.)

- [ ] **Step 2: Run tests + typecheck**

```bash
cd frontend && pnpm test src/core/workflows && pnpm typecheck && pnpm lint src/core/workflows
```
Expected: green, clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/workflows/hooks.ts
git commit -m "feat(frontend): invalidate chat list when active workflow count drops"
```

---

### Task B9: Final integration smoke + status doc

**Files:**
- Modify: `docs/superpowers/STATUS-2026-04-28.md`

- [ ] **Step 1: Run full backend + frontend test suites**

```bash
cd backend && uv run ruff check . && uv run pytest tests/
cd ../frontend && pnpm lint && pnpm typecheck && pnpm test
```
Expected: all green.

- [ ] **Step 2: End-to-end manual smoke**

1. `make dev` (or `make dev-pro`) — full stack on `localhost:2026`
2. Open browser → new chat thread A
3. Ask the LLM to `start_workflow("demo-flow", {"task_name": "x"})`
4. Within 2s, sidebar bottom shows "Active workflows (1)" with `demo-flow` row, progress updating
5. Open thread B in a new tab; sidebar there shows no workflow
6. Back in A, click `[×]` on the row → row disappears within ~2s, chat shows `[workflow:demo-flow] cancelled by user`
7. Start another workflow on A; switch to B (don't wait for A to finish); wait ~30s; switch back to A — A's workflow should be done by now → red dot was visible on A in the sidebar while you were in B; now back in A, dot is gone
8. Refresh page on B → no red dots (session-only)

If any step fails, file a bug, fix, re-run. Don't proceed to Step 3 until all 8 pass.

- [ ] **Step 3: Update STATUS doc**

Append a section to `docs/superpowers/STATUS-2026-04-28.md` documenting Phase 2 landing:

```markdown
## Phase 2 — Frontend Child Workflow Widget (DONE)

Landed: <date>

- Backend: `GET /api/threads/{tid}/workflows/active` returns running children with progress projection
- Backend: `POST /api/threads/{tid}/workflows/{cid}/cancel` for user-initiated cancel without LLM
- Backend: `stamp_parent_finish` writes `recent_workflow_finish_at` into parent metadata at terminal events
- Frontend: `useActiveWorkflows` (2s polling), `useCancelActiveWorkflow`
- Frontend: `useThreadViewed` zustand store + `hasUnreadFinish` pure helper (session-only red dot)
- Frontend: `ActiveWorkflowsPanel` mounted in workspace sidebar; renders nothing when no active workflows
- Frontend: red dot on chat-list items whose `recent_workflow_finish_at > lastViewedAt[tid]`

Smoke tests: 8/8 passed (see plan Task B9). Backend tests: <count>. Frontend tests: <count>.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/STATUS-2026-04-28.md
git commit -m "docs(workflows): Phase 2 landed — child workflow widget"
```

---

## Open Items Deferred to Phase 3+

- chat-list polling: relying on stream-finish + active-workflows-shrink invalidation. If real users find the red dot lag too long (e.g. multiple workflows on a thread that the user never visits), revisit with low-frequency `useThreads` `refetchInterval`.
- Cross-device sync of "viewed" state: explicitly out of scope (Q7-C).
- Click-to-progress-message in widget (spec §5.2): deferred. Today the user can ask the LLM `get_workflow_progress` for the same info; the widget already shows round numbers. If product wants it later, add a row click → push ephemeral message via a new `useChatLocalMessages()` context.
- "Possibly orphaned" detection (Phase 1 §8.3): unchanged, still future work.
