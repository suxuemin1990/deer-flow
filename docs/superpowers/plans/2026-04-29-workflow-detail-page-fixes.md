# Workflow Detail Page — Bug 5 Fix + Progress Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Bug 5 (running-workflow injections lose `HumanMessage`) and add a progress-timeline panel to the workflow detail page so non-LLM polling workflows have a visible dynamic body.

**Architecture:**

- **Stage A** restores `hints_inbox` as a *side-channel* that coexists with the `messages` channel. While a workflow is running, injection writes only to the inbox (in-memory, immediately visible to the running task). The workflow's own loop node drains the inbox each tick and emits new `HumanMessage`s through node return values, so the `add_messages` reducer merges them into checkpointed state without a write race against the running pregel. Terminal-state injection still uses `aupdate_state` (works fine, no race).
- **Stage B** adds a `progress_timeline_fields: list[str]` field to `WorkflowSpec`. When non-empty, the detail page renders a Timeline panel (option A: time-line list, one row per `history` entry) above the chat panel. demo-flow declares `progress_timeline_fields: ["history"]`; LLM-only workflows can leave it empty.

The two stages are independent: Stage A is a backend-only correctness fix; Stage B is mostly frontend with one tiny spec change. Either can be reviewed and shipped first.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, langchain-core; Next.js 16 / React 19 / TanStack Query.

---

## File Structure

### Stage A files

- Create / restore: `backend/packages/harness/deerflow/workflows/hints_inbox.py`
- Modify: `backend/packages/harness/deerflow/workflows/emit.py` — branch on running vs terminal
- Modify: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py` — drain inbox at tick start
- Create: `backend/tests/test_hints_inbox.py` — unit tests for the inbox primitives
- Create: `backend/tests/test_inject_during_running_workflow.py` — end-to-end repro of Bug 5 + verify fix
- Modify: `backend/tests/test_hints_inbox_removed.py` — DELETE (the regression that asserted removal is now obsolete)
- Modify: `backend/packages/harness/deerflow/workflows/base_state.py` — update docstring
- Modify: `frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx` — show optimistic pending bubbles so the user sees their hint immediately

### Stage B files

- Modify: `backend/packages/harness/deerflow/workflows/registry.py` — add `progress_timeline_fields: list[str]` field
- Modify: `config.example.yaml` — add `progress_timeline_fields: [history]` for demo-flow
- Modify: `backend/app/gateway/routers/workflows_hub.py` — include timeline data in `/api/workflows/all` (optional; or fetch via state endpoint per-detail-page)
- Create: `frontend/src/app/workspace/workflows/[child_thread_id]/_components/progress-timeline.tsx`
- Modify: `frontend/src/app/workspace/workflows/[child_thread_id]/page.tsx` — render Timeline above ChatPanel when spec declares it
- Modify: `frontend/src/core/workflows/types.ts` — extend `WorkflowEntry` with `timeline?: TimelineEntry[]`
- Modify: `backend/tests/test_workflows_hub_endpoint.py` — verify timeline is exposed
- Create: `frontend/tests/unit/components/workspace/workflows/progress-timeline.test.tsx`

Each file has one clear responsibility. Files that change together stay together (e.g. work_loop_node + its tests).

---

# Stage A — Fix Bug 5 (Running-Workflow Injection Loses Messages)

## Background for the engineer

You are touching a LangGraph + FastAPI codebase. Some context you need:

- **LangGraph checkpointer**: a workflow's state is persisted to a `BaseCheckpointSaver` (SQLite in production, `InMemorySaver` in tests). Each "step" of a running graph writes a checkpoint. State is a `TypedDict` whose fields are *channels*; channels with `Annotated[..., reducer]` are merged via the reducer when multiple writes target the same channel.
- **The bug**: `inject_user_message_to_workflow(...)` calls `graph.aupdate_state(values={"messages": [HumanMessage(...)]})`. This commits a sibling checkpoint. But the *running* `graph.ainvoke()` task already loaded its in-memory channel view at start; on its next step it commits a checkpoint based on that stale view, overwriting the inject. Verified empirically: SQLite drops the message; InMemorySaver (where reads share the dict) does not.
- **The fix**: don't fight the running task. Instead, hand the hint to the running task itself via a process-local inbox, and let *the workflow's own node* emit the `HumanMessage` through its return value. Node returns flow through reducers normally, so `messages` gets `add_messages`-merged into the next checkpoint. No race.
- **Coexistence with messages channel**: the `messages` channel still exists and is the canonical chat history. The inbox is just a *transport* from POST handler → running task. After drain, the message lives in `messages` like any other.

You will see references to `_BG_TASKS: dict[str, asyncio.Task]` in `workflows/tools.py` — this is how we know whether a child thread has a running task. Use `child_thread_id in _BG_TASKS` as the "is running" predicate.

---

## Task A1: Create the hints_inbox module

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/hints_inbox.py`
- Create: `backend/tests/test_hints_inbox.py`

**Why this task:** A tiny dedicated module so the inject path and the drain path share one source of truth. Process-local (no persistence) — if gateway restarts mid-run, hints in-flight are lost, which is acceptable because mid-run cancel happens on restart anyway.

- [ ] **Step A1.1: Write the failing inbox tests**

```python
# backend/tests/test_hints_inbox.py
"""Unit tests for workflows.hints_inbox.

The inbox is a process-local async-safe queue keyed by workflow child
thread id. POST handlers push hints; running workflow nodes drain them.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_push_then_pop_all_returns_in_order():
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    await ib.push("tid-1", "first")
    await ib.push("tid-1", "second")
    drained = await ib.pop_all("tid-1")
    assert [h.content for h in drained] == ["first", "second"]


@pytest.mark.asyncio
async def test_pop_all_when_empty_returns_empty_list():
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    drained = await ib.pop_all("tid-empty")
    assert drained == []


@pytest.mark.asyncio
async def test_pop_all_is_atomic_drain():
    """After pop_all, the queue is empty for that thread."""
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    await ib.push("tid-2", "a")
    await ib.pop_all("tid-2")
    assert await ib.pop_all("tid-2") == []


@pytest.mark.asyncio
async def test_per_thread_isolation():
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    await ib.push("tid-A", "for A")
    await ib.push("tid-B", "for B")
    drained_a = await ib.pop_all("tid-A")
    drained_b = await ib.pop_all("tid-B")
    assert [h.content for h in drained_a] == ["for A"]
    assert [h.content for h in drained_b] == ["for B"]


@pytest.mark.asyncio
async def test_pushed_hints_carry_stable_ids():
    """Each push generates a stable id, returned in the InboxHint dataclass.

    Workflow nodes use this id when constructing HumanMessage so the
    frontend can dedupe optimistic UI bubbles against polled state.
    """
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    h_id = await ib.push("tid-3", "hello")
    drained = await ib.pop_all("tid-3")
    assert len(drained) == 1
    assert drained[0].id == h_id
    assert drained[0].content == "hello"


@pytest.mark.asyncio
async def test_concurrent_push_and_pop_no_loss():
    """Async-safe: 50 concurrent pushers + 1 popper, no message lost."""
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()

    async def pusher(i: int) -> None:
        await ib.push("tid-c", f"msg-{i}")

    await asyncio.gather(*(pusher(i) for i in range(50)))
    drained = await ib.pop_all("tid-c")
    assert sorted(h.content for h in drained) == sorted(f"msg-{i}" for i in range(50))
```

- [ ] **Step A1.2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_hints_inbox.py -v
```

Expected: FAIL with `ModuleNotFoundError: deerflow.workflows.hints_inbox`.

- [ ] **Step A1.3: Implement the inbox module**

Create `backend/packages/harness/deerflow/workflows/hints_inbox.py`:

```python
"""Process-local async-safe inbox for runtime hint injection.

The Workflow Hub UI / inject_hint tool POSTs a hint; the POST handler
calls :func:`push`. The running workflow's loop node calls
:func:`pop_all` at each tick, drains pending hints, and emits them as
HumanMessages through its node return value. Because the running pregel
itself is the writer, its next checkpoint commit naturally includes the
new messages via the ``add_messages`` reducer — no race with sibling
checkpoints written via ``aupdate_state``.

Why not just write through ``messages`` channel directly:
    See bug 5 in the 2026-04-29 smoke doc. Briefly: the running task
    holds an in-memory channel view; sibling checkpoints written via
    ``aupdate_state`` are overwritten by the next step's commit.

Why process-local (no persistence):
    A hint pending at gateway restart was always going to be lost
    anyway — the running workflow task itself dies with the process.
    Keeping the inbox in-memory avoids a second source of truth and
    sidesteps SQLite write contention.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

# Module-level state. Reset only via reset_for_test().
_INBOX: dict[str, list["InboxHint"]] = {}
_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class InboxHint:
    """A pending hint waiting to be drained by a running workflow.

    Attributes:
        id: Stable unique id. The workflow node MUST use this as the
            HumanMessage id when constructing the message, so frontend
            optimistic bubbles can dedupe against polled state.
        content: User-supplied hint text.
    """

    id: str
    content: str


async def push(child_thread_id: str, content: str) -> str:
    """Append a hint to the inbox; return its stable id."""
    hint = InboxHint(id=str(uuid.uuid4()), content=content)
    async with _LOCK:
        _INBOX.setdefault(child_thread_id, []).append(hint)
    return hint.id


async def pop_all(child_thread_id: str) -> list[InboxHint]:
    """Atomically drain all pending hints for a thread.

    Returns an empty list if the thread has no pending hints.
    """
    async with _LOCK:
        return _INBOX.pop(child_thread_id, [])


def reset_for_test() -> None:
    """Wipe inbox state. Test-only."""
    _INBOX.clear()
```

- [ ] **Step A1.4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_hints_inbox.py -v
```

Expected: 6 tests pass.

- [ ] **Step A1.5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/hints_inbox.py backend/tests/test_hints_inbox.py
git commit -m "$(cat <<'EOF'
feat(workflows): restore hints_inbox as side-channel for runtime injection

Coexists with the messages channel: inbox is the transport from POST
handler to running task; messages is still the persisted chat history.
Running task drains inbox and emits HumanMessage via node return so the
add_messages reducer merges cleanly without racing the running pregel.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

## Task A2: Route inject_user_message_to_workflow through the inbox when running

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/emit.py:71-110`
- Modify: `backend/packages/harness/deerflow/workflows/base_state.py:25-27` — docstring update
- Create: `backend/tests/test_inject_during_running_workflow.py`

- [ ] **Step A2.1: Write the failing end-to-end test**

This test is the regression for Bug 5. It must use a SQLite checkpointer (not InMemory) to reproduce the race.

```python
# backend/tests/test_inject_during_running_workflow.py
"""Bug 5 regression — injection during a running workflow must persist.

Before fix: aupdate_state from inject_user_message_to_workflow wrote a
sibling checkpoint; running pregel's next step overwrote it; messages
lost. After fix: POST routes to hints_inbox while running task drains it
and emits HumanMessages via node return.

Uses AsyncSqliteSaver to match production; InMemorySaver shares dicts
across reads/writes and would not reproduce the race.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_inject_during_running_workflow_persists_message(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows import emit as emit_mod
    from deerflow.workflows import hints_inbox as ib
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.tools import start_workflow

    db = tmp_path / "checkpoints.sqlite"
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        set_default_checkpointer(saver)
        ib.reset_for_test()

        registry = WorkflowRegistry(
            specs=[WorkflowSpec(
                name="demo-flow",
                description="d",
                factory=make_graph,
                input_schema=DemoFlowInput,
                done_field="is_done",
                report_field="report_markdown",
                progress_fields=["current_round", "max_rounds", "history"],
                accepts_chat=True,
            )],
            failures=[],
        )
        original = tools_mod._get_registry
        tools_mod._get_registry = lambda: registry  # noqa: SLF001
        try:
            # Seed parent thread (so start_workflow has somewhere to emit notices)
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, START, MessagesState, StateGraph

            g = StateGraph(MessagesState)
            g.add_node("noop", lambda s: s)
            g.add_edge(START, "noop")
            g.add_edge("noop", END)
            await g.compile(checkpointer=saver).ainvoke(
                {"messages": [HumanMessage(content="hi")]},
                config={"configurable": {"thread_id": "p-1"}},
            )

            # Start a slow workflow (max_rounds high enough to leave it
            # running while we inject; demo-flow's poll_wait sleeps 2s).
            result = await start_workflow.ainvoke(
                {
                    "name": "start_workflow",
                    "args": {
                        "name": "demo-flow",
                        "params": {"task_name": "x", "max_rounds": 5},
                    },
                    "id": "h-1",
                    "type": "tool_call",
                },
                config={"configurable": {"thread_id": "p-1"}},
            )
            import re
            child_tid = re.search(
                r"thread_id=([0-9a-f-]+)", result.update["messages"][0].content
            ).group(1)

            # Wait for the workflow to actually start ticking (at least 1 round).
            for _ in range(30):
                await asyncio.sleep(0.2)
                cp = await saver.aget_tuple(
                    {"configurable": {"thread_id": child_tid, "checkpoint_ns": ""}}
                )
                if cp and (cp.checkpoint or {}).get("channel_values", {}).get("current_round", 0) >= 1:
                    break

            # Inject while running.
            await emit_mod.inject_user_message_to_workflow(
                child_tid,
                "please refine — try smaller lr",
                spec=registry.get("demo-flow"),
                checkpointer=saver,
            )

            # Wait for workflow to complete (poll_wait * remaining rounds < 15s).
            task = tools_mod._BG_TASKS.get(child_tid)
            if task is not None:
                await asyncio.wait_for(asyncio.shield(task), timeout=20)

            # Verify HumanMessage with our content survives in final state.
            graph = make_graph(checkpointer=saver)
            final = await graph.aget_state(
                {"configurable": {"thread_id": child_tid}}
            )
            from langchain_core.messages import HumanMessage as _HM
            msgs = final.values.get("messages") or []
            assert any(
                isinstance(m, _HM) and "smaller lr" in m.content for m in msgs
            ), f"expected injected HumanMessage to persist; got {msgs!r}"
        finally:
            tools_mod._get_registry = original
            reset_default_checkpointer()
            ib.reset_for_test()
```

- [ ] **Step A2.2: Run the test to verify it fails (Bug 5 reproduction)**

```bash
cd backend && uv run pytest tests/test_inject_during_running_workflow.py -v
```

Expected: FAIL with `AssertionError: expected injected HumanMessage to persist`. This is the bug.

- [ ] **Step A2.3: Modify inject_user_message_to_workflow to branch on running state**

Open `backend/packages/harness/deerflow/workflows/emit.py` and replace lines 71-110 with:

```python
async def inject_user_message_to_workflow(
    child_thread_id: str,
    content: str,
    *,
    spec,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Append a HumanMessage to a workflow child thread.

    Routing depends on whether the child currently has a running task:

    - **Running** (``child_thread_id in _BG_TASKS``): push to
      :mod:`hints_inbox`. The running workflow's loop node drains
      it next tick and emits a HumanMessage via its node return,
      so ``add_messages`` reducer merges cleanly. We CANNOT use
      ``aupdate_state`` here — it commits a sibling checkpoint that
      the running pregel's next step overwrites (Bug 5).

    - **Terminal**: write directly via ``aupdate_state``. No running
      task means no race; this is the simple path used to keep
      bidirectional chat working after completion.

    Why we use the caller-supplied workflow spec for the terminal
    branch: SQLite checkpointer only serializes channels declared
    on the schema being used to write. Writing HumanMessage via a
    graph compiled against ``ThreadState`` (channels = messages,
    title, thread_data, artifacts) silently drops every
    workflow-specific field on the next checkpoint — wiping the
    workflow's state. By using ``spec.factory(checkpointer=...)``,
    the appender graph has the workflow's real TypedDict and every
    channel survives.

    Args:
        child_thread_id: Target child workflow thread.
        content: Free-text user instruction.
        spec: The :class:`WorkflowSpec` of the workflow on
            ``child_thread_id``. The caller is responsible for looking
            it up; passing a spec from a different workflow would
            corrupt state.
        checkpointer: Shared checkpointer.
    """
    from langchain_core.messages import HumanMessage

    # Lazy import to avoid a startup cycle:
    # workflows.tools imports workflows.emit (start_workflow), so
    # emit at module-load can't import tools.
    from deerflow.workflows.tools import _BG_TASKS
    from deerflow.workflows import hints_inbox

    if child_thread_id in _BG_TASKS:
        # Running: side-channel.
        await hints_inbox.push(child_thread_id, content)
        return

    # Terminal: direct write is safe.
    appender = spec.factory(checkpointer=checkpointer)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": child_thread_id}},
        values={"messages": [HumanMessage(content=content)]},
        as_node="__start__",
    )
```

- [ ] **Step A2.4: Update work_loop_node to drain inbox at tick start**

Open `backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py` and replace its body with:

```python
"""Increment round counter; consume any new injected HumanMessages.

Hints arrive via two paths and are unified into ``state['messages']``:

1. **Inbox drain** (running-time injection, Bug 5 fix): we ask
   :mod:`hints_inbox` for any pending hints for our thread id. New
   hints are emitted as HumanMessages through this node's return value,
   so ``add_messages`` merges them into the next checkpoint and the
   running pregel itself is the writer (no overwrite race).

2. **Direct messages-channel writes** (terminal-state injection,
   inject_hint tool, etc.): land in ``state['messages']`` already; we
   just filter by ``state['_seen_msg_ids']`` to avoid re-feeding the
   inner LLM each tick.

Demo_flow does nothing semantic with hints — it only proves the
delivery pipe works end-to-end. Real workflows should feed the new
HumanMessages into their inner LLM and let the LLM react.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from deerflow.workflows import hints_inbox


async def work_loop_node(state, config: RunnableConfig):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}

    update: dict = {"current_round": current + 1, "is_done": False}

    # 1. Drain inbox: hints injected while running land here.
    child_tid = (config or {}).get("configurable", {}).get("thread_id", "")
    new_inbox_msgs: list[HumanMessage] = []
    if child_tid:
        drained = await hints_inbox.pop_all(child_tid)
        new_inbox_msgs = [
            HumanMessage(id=h.id, content=h.content) for h in drained
        ]
    if new_inbox_msgs:
        # add_messages reducer will merge into state.messages
        update["messages"] = new_inbox_msgs

    # 2. Filter messages channel for unseen HumanMessages (covers both
    #    the new inbox emissions above AND any terminal-state direct writes).
    seen = state.get("_seen_msg_ids") or set()
    msgs = state.get("messages") or []
    # Include the just-emitted inbox msgs in the "new" set even though
    # they aren't in state yet (the merge happens after this return).
    candidate_msgs = list(msgs) + new_inbox_msgs
    new_human_msgs = [
        m for m in candidate_msgs
        if isinstance(m, HumanMessage) and getattr(m, "id", None) not in seen
    ]
    if new_human_msgs:
        update["history"] = [{
            "round": current + 1,
            "hints": [m.content for m in new_human_msgs],
        }]
        update["_seen_msg_ids"] = seen | {
            m.id for m in new_human_msgs if getattr(m, "id", None)
        }
    return update
```

- [ ] **Step A2.5: Run the regression test to verify it passes**

```bash
cd backend && uv run pytest tests/test_inject_during_running_workflow.py -v
```

Expected: PASS — the injected HumanMessage with content "smaller lr" is present in final state.

- [ ] **Step A2.6: Run the existing inbox tests + the existing inject_hint test together**

```bash
cd backend && uv run pytest tests/test_hints_inbox.py tests/test_workflows_tools.py -v
```

Expected: all pass. The existing `test_inject_hint_writes_human_message_via_messages_channel` still works because in that test the workflow has not been ticked through `work_loop_node` yet (the node uses inbox drain, but that test only exercises the inject side, then asserts via direct state read after the inject — and the direct write path is preserved in terminal mode; the test uses InMemorySaver and doesn't actually start a running task that would push the route into "running" branch).

(If that test fails due to the running/terminal branching, fix by ensuring the test cancels its background task before assertion, OR adjust the test to drain inbox manually. Show the failure, then patch.)

- [ ] **Step A2.7: Update base_state.py docstring**

In `backend/packages/harness/deerflow/workflows/base_state.py`, replace lines 25-27 (the "Hints no longer flow through hints_inbox" sentence):

```python
Hints flow through one of two paths depending on workflow state:

- **Running**: POST handler pushes to :mod:`hints_inbox`; the
  workflow's loop node drains and emits HumanMessages via node
  return so ``add_messages`` merges cleanly without overwrite race.
- **Terminal**: direct ``aupdate_state`` write to the ``messages``
  channel (no race because no running task).

Both paths land in ``state['messages']`` from the workflow author's
point of view; they need to filter by ``_seen_msg_ids`` to avoid
re-feeding the inner LLM on every tick.
```

- [ ] **Step A2.8: Delete the obsolete regression test**

```bash
rm backend/tests/test_hints_inbox_removed.py
```

This test asserted that the module no longer exists. Now it does. Removing it is correct.

- [ ] **Step A2.9: Run the full backend test suite**

```bash
cd backend && uv run pytest -x
```

Expected: all pass (modulo the deleted test).

- [ ] **Step A2.10: Run lint**

```bash
cd backend && uv run ruff check .
```

Expected: clean.

- [ ] **Step A2.11: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/emit.py \
        backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py \
        backend/packages/harness/deerflow/workflows/base_state.py \
        backend/tests/test_inject_during_running_workflow.py
git rm backend/tests/test_hints_inbox_removed.py
git commit -m "$(cat <<'EOF'
fix(workflows): route running-time injection through hints_inbox to fix Bug 5

inject_user_message_to_workflow now branches on whether the child has
a running task. Running -> push to inbox; the workflow's own loop node
drains and emits HumanMessage via node return so add_messages reducer
merges into the next checkpoint. Terminal -> direct aupdate_state as
before. Adds an end-to-end regression with AsyncSqliteSaver that
reproduces the SQLite-only race.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

## Task A3: Frontend optimistic pending bubble

When the user hits Send, today the textarea clears but nothing appears until polling fetches updated state — and on running workflows, that could be 1-2 ticks (4-6s with default 2s poll_wait). Show a local optimistic bubble immediately, and dedupe against polled state when it arrives.

**Files:**
- Modify: `frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx`

- [ ] **Step A3.1: View the file to copy current structure**

```bash
# Use the View tool, not cat:
view /data/src/deer-flow/frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx
```

- [ ] **Step A3.2: Add pending-bubble state and dedup logic**

In the same file, modify the component body. Locate the `const { messages, isLoading, send, isSending } = useWorkflowChat(...)` line and insert pending-bubble state right after it. Then merge into the rendered list.

Replace this block:

```tsx
  const { messages, isLoading, send, isSending } = useWorkflowChat(
    parentThreadId,
    workflow.child_thread_id,
  );
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
```

with:

```tsx
  const { messages, isLoading, send, isSending } = useWorkflowChat(
    parentThreadId,
    workflow.child_thread_id,
  );
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // Optimistic local pending hints. Appear immediately on send; clear
  // when an equivalent server message arrives via polling. Match by
  // exact content + role==human; not perfect (rapid duplicates would
  // collapse) but the running-workflow inject path is human-paced.
  const [pendingHints, setPendingHints] = useState<
    { id: string; content: string; sentAt: number }[]
  >([]);

  // Drop pending hints once the server confirms them.
  useEffect(() => {
    if (pendingHints.length === 0) return;
    setPendingHints((prev) =>
      prev.filter(
        (p) =>
          !messages.some(
            (m) => m.role === "human" && m.content === p.content,
          ),
      ),
    );
  }, [messages, pendingHints.length]);
```

Then locate the messages render loop and replace it. Find:

```tsx
        {messages.map((m, i) => {
```

Replace the entire `{messages.map(...)}` block with a merged renderer that interleaves pendingHints at the bottom:

```tsx
        {messages.map((m, i) => {
          const isUser = m.role === "human";
          const ack = isUser ? ackFor(m, i, messages) : null;
          return (
            <div
              key={m.id || `${m.role}-${i}`}
              className={`flex ${isUser ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  isUser
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                }`}
              >
                <div className="whitespace-pre-wrap">{m.content}</div>
                {ack && (
                  <div className="mt-1 flex justify-end gap-0.5 opacity-70">
                    {ack === "consumed" ? (
                      <CheckCheckIcon className="size-3" />
                    ) : (
                      <CheckIcon className="size-3" />
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {pendingHints.map((p) => (
          <div
            key={`pending-${p.id}`}
            className="flex justify-end"
            data-testid="pending-hint-bubble"
          >
            <div className="bg-primary text-primary-foreground max-w-[80%] rounded-lg px-3 py-2 text-sm opacity-60">
              <div className="whitespace-pre-wrap">{p.content}</div>
              <div className="mt-1 flex justify-end gap-0.5 opacity-70">
                <span className="text-xs">sending…</span>
              </div>
            </div>
          </div>
        ))}
```

Then update the two `send(draft.trim())` callers to also push into pendingHints:

```tsx
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                const text = draft.trim();
                if (text) {
                  send(text);
                  setPendingHints((prev) => [
                    ...prev,
                    { id: crypto.randomUUID(), content: text, sentAt: Date.now() },
                  ]);
                  setDraft("");
                }
              }
            }}
```

and the button onClick:

```tsx
            onClick={() => {
              const text = draft.trim();
              if (text) {
                send(text);
                setPendingHints((prev) => [
                  ...prev,
                  { id: crypto.randomUUID(), content: text, sentAt: Date.now() },
                ]);
                setDraft("");
              }
            }}
```

- [ ] **Step A3.3: Run frontend typecheck and lint**

```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: clean.

- [ ] **Step A3.4: Manual smoke (optional but recommended)**

If gateway is up, navigate to a running workflow detail page, send a message, observe:
- Pending bubble appears at bottom with `sending…` and reduced opacity within ~50ms.
- Within ~3-6 seconds, polled state catches up; pending bubble disappears as the canonical bubble takes its place.

- [ ] **Step A3.5: Commit**

```bash
git add frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx
git commit -m "$(cat <<'EOF'
feat(workflows): optimistic pending hint bubble in detail page

Send no longer leaves the user staring at an unchanged screen until
the next poll. Pending hint shows immediately with reduced opacity +
"sending…" label; clears when polled state contains an equivalent
HumanMessage.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

# Stage B — Progress Timeline Panel

Stage B is independent of Stage A. It can be reviewed and merged separately. The two stages cooperate (Stage A makes hint history visible in messages; Stage B makes round/score progress visible in a timeline) but neither needs the other to land first.

---

## Task B1: Add progress_timeline_fields to WorkflowSpec + config

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/registry.py:32-43, 70-81`
- Modify: `config.example.yaml` — add timeline fields to demo-flow entry

- [ ] **Step B1.1: Write failing registry test**

```python
# Append to backend/tests/test_registry.py if it exists, otherwise create.
# Filename to use if creating: backend/tests/test_registry_timeline_fields.py

import pytest


def test_workflow_spec_carries_progress_timeline_fields():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "tl",
        "description": "d",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
        "progress_fields": ["current_round"],
        "progress_timeline_fields": ["history"],
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    spec = reg.get("tl")
    assert spec.progress_timeline_fields == ["history"]


def test_workflow_spec_progress_timeline_fields_defaults_empty():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "tl2",
        "description": "d",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    assert reg.get("tl2").progress_timeline_fields == []
```

- [ ] **Step B1.2: Run test to verify failure**

```bash
cd backend && uv run pytest tests/test_registry_timeline_fields.py -v
```

Expected: FAIL with `AttributeError: 'WorkflowSpec' object has no attribute 'progress_timeline_fields'`.

- [ ] **Step B1.3: Add the field to WorkflowSpec**

In `backend/packages/harness/deerflow/workflows/registry.py`, locate the `WorkflowSpec` dataclass (around line 33) and add `progress_timeline_fields` after `progress_fields`:

```python
@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    description: str
    factory: Callable[..., Any]
    input_schema: type[BaseModel]
    done_field: str
    report_field: str
    progress_fields: list[str] = field(default_factory=list)
    progress_timeline_fields: list[str] = field(default_factory=list)
    hint_behavior_doc: str = ""
    accepts_chat: bool = False
```

Then in `load_from_dicts` (around line 70-81), pass it in when constructing the spec:

```python
                specs.append(WorkflowSpec(
                    name=item["name"],
                    description=item["description"],
                    factory=factory,
                    input_schema=input_schema,
                    done_field=item["done_field"],
                    report_field=item["report_field"],
                    progress_fields=list(item.get("progress_fields") or []),
                    progress_timeline_fields=list(
                        item.get("progress_timeline_fields") or []
                    ),
                    hint_behavior_doc=item.get("hint_behavior_doc") or "",
                    accepts_chat=bool(item.get("accepts_chat", False)),
                ))
```

- [ ] **Step B1.4: Add timeline fields to demo-flow in config.example.yaml**

Locate the `demo-flow` entry in `config.example.yaml` (around line 1000-ish; search for `name: demo-flow`). Add `progress_timeline_fields: [history]` between `progress_fields:` and `accepts_chat:`:

```yaml
    progress_fields: [current_round, max_rounds, history]
    progress_timeline_fields: [history]
    accepts_chat: true
```

- [ ] **Step B1.5: Run test to verify pass**

```bash
cd backend && uv run pytest tests/test_registry_timeline_fields.py -v
```

Expected: PASS.

- [ ] **Step B1.6: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/registry.py \
        backend/tests/test_registry_timeline_fields.py \
        config.example.yaml
git commit -m "$(cat <<'EOF'
feat(workflows): add progress_timeline_fields to WorkflowSpec

Lists state field names whose values should drive a progress-timeline
panel in the detail page. demo-flow declares ["history"] so each
{round, score} entry becomes a timeline row.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

## Task B2: Expose timeline data in /api/workflows/all + state endpoint

The detail page already polls `/api/threads/{cid}/state`, which returns full `values`. Timeline data is already there for free — we just need the spec metadata exposed so the frontend knows *which* fields are timeline fields. Two cheap options:

- **Option α** (simpler): expose `progress_timeline_fields` per workflow entry in `/api/workflows/all` response. Frontend looks it up when rendering detail.
- **Option β**: a dedicated `GET /api/workflows/{name}/spec` endpoint.

We'll do α — the hub aggregator is already the only place the frontend learns about workflows, and detail page already finds its `WorkflowEntry` by walking the hub tree.

**Files:**
- Modify: `backend/app/gateway/routers/workflows_hub.py` — include `progress_timeline_fields` in entry serialization
- Modify: `backend/tests/test_workflows_hub_endpoint.py` — assert it's exposed

- [ ] **Step B2.1: Write failing hub-endpoint test**

In `backend/tests/test_workflows_hub_endpoint.py`, add:

```python
@pytest.mark.asyncio
async def test_hub_response_exposes_progress_timeline_fields(client_with_workflow):
    # client_with_workflow: existing fixture; check its name in this file
    # and adapt if needed. Look for fixtures used by other tests.
    response = await client_with_workflow.get("/api/workflows/all")
    body = response.json()
    parents = body["parents"]
    assert parents
    workflows = parents[0]["workflows"]
    assert workflows
    # demo-flow registered with progress_timeline_fields=["history"]
    assert workflows[0]["progress_timeline_fields"] == ["history"]
```

(The fixture name will already exist in the file; use `view` to copy the actual name. If the fixture doesn't seed timeline fields by default, modify the registration in the fixture too — show the diff.)

- [ ] **Step B2.2: Run test to verify failure**

```bash
cd backend && uv run pytest tests/test_workflows_hub_endpoint.py::test_hub_response_exposes_progress_timeline_fields -v
```

Expected: FAIL — KeyError or assertion failure.

- [ ] **Step B2.3: Add the field to hub serialization**

In `backend/app/gateway/routers/workflows_hub.py`, find the `wf_entries.append({...})` block (around line 150) and add `"progress_timeline_fields": list(spec.progress_timeline_fields),` between `"progress"` and `"report_preview"`:

```python
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
                "report_preview": _truncate(report, _REPORT_PREVIEW_LEN),
                "error": _truncate(error, _ERROR_PREVIEW_LEN),
            })
```

- [ ] **Step B2.4: Run test to verify pass**

```bash
cd backend && uv run pytest tests/test_workflows_hub_endpoint.py -v
```

Expected: PASS (this and all other tests in the file).

- [ ] **Step B2.5: Run full backend tests + lint**

```bash
cd backend && uv run pytest -x && uv run ruff check .
```

Expected: clean.

- [ ] **Step B2.6: Commit**

```bash
git add backend/app/gateway/routers/workflows_hub.py \
        backend/tests/test_workflows_hub_endpoint.py
git commit -m "$(cat <<'EOF'
feat(workflows-hub): expose progress_timeline_fields in /api/workflows/all

Frontend detail page can read which state fields drive its timeline
panel without a separate spec lookup endpoint.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

## Task B3: Frontend types + the timeline panel component

**Files:**
- Modify: `frontend/src/core/workflows/types.ts` — extend `WorkflowEntry`
- Create: `frontend/src/app/workspace/workflows/[child_thread_id]/_components/progress-timeline.tsx`
- Create: `frontend/tests/unit/components/workspace/workflows/progress-timeline.test.tsx`

The Timeline panel renders one row per entry in `state[fieldName]` (where fieldName is one of the spec's `progress_timeline_fields`; for demo-flow this is `"history"`). Each row shows:

- A left-edge dot (filled blue for the most recent row, hollow for older)
- A middle text block: each scalar field formatted as `key=value` joined by `·`. Nested objects render as `JSON.stringify(value)` (collapsed JSON). HumanMessage-bearing entries (with `hints` array) get a 💬 icon prefix.
- A right-edge relative timestamp ("2s ago") if the entry has a `ts`/`timestamp` field; omitted otherwise (demo-flow's history entries don't have timestamps, so omit gracefully).

Layout: **Option A (chosen by user)** — vertical timeline list, newest at bottom. Auto-scroll to bottom on new entry. Max-height ~40vh; overflow scroll.

- [ ] **Step B3.1: Extend WorkflowEntry type**

In `frontend/src/core/workflows/types.ts`, find `export interface WorkflowEntry` and add the field:

```ts
export interface WorkflowEntry {
  child_thread_id: string;
  name: string;
  status: WorkflowStatus;
  started_at: string | null;
  finished_at: string | null;
  progress: Record<string, unknown>;
  progress_timeline_fields: string[];  // <-- ADD
  report_preview: string | null;
  error: string | null;
}
```

- [ ] **Step B3.2: Write failing component test**

Create `frontend/tests/unit/components/workspace/workflows/progress-timeline.test.tsx`:

```tsx
import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";

import { ProgressTimeline } from "@/app/workspace/workflows/[child_thread_id]/_components/progress-timeline";

describe("ProgressTimeline", () => {
  test("renders nothing when fields list is empty", () => {
    const { container } = render(
      <ProgressTimeline values={{}} fields={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  test("renders nothing when target field is empty list", () => {
    const { container } = render(
      <ProgressTimeline values={{ history: [] }} fields={["history"]} />,
    );
    // Empty-state placeholder is acceptable; assert it doesn't crash
    expect(container.textContent).toMatch(/no progress yet/i);
  });

  test("renders one row per history entry with scalar fields", () => {
    render(
      <ProgressTimeline
        values={{
          history: [
            { round: 1, score: 0.5 },
            { round: 2, score: 0.7 },
          ],
        }}
        fields={["history"]}
      />,
    );
    expect(screen.getByText(/round=1/)).toBeInTheDocument();
    expect(screen.getByText(/score=0\.5/)).toBeInTheDocument();
    expect(screen.getByText(/round=2/)).toBeInTheDocument();
    expect(screen.getByText(/score=0\.7/)).toBeInTheDocument();
  });

  test("hint entries render with 💬 prefix", () => {
    render(
      <ProgressTimeline
        values={{
          history: [
            { round: 1, hints: ["try smaller lr"] },
          ],
        }}
        fields={["history"]}
      />,
    );
    expect(screen.getByText(/💬/)).toBeInTheDocument();
    expect(screen.getByText(/try smaller lr/)).toBeInTheDocument();
  });

  test("nested objects render as collapsed JSON", () => {
    render(
      <ProgressTimeline
        values={{
          history: [{ round: 1, metrics: { loss: 0.1, acc: 0.9 } }],
        }}
        fields={["history"]}
      />,
    );
    // We render `metrics={"loss":0.1,"acc":0.9}` (or similar)
    expect(screen.getByText(/metrics=/)).toBeInTheDocument();
    expect(screen.getByText(/loss/)).toBeInTheDocument();
  });

  test("most recent row gets filled dot, older rows hollow", () => {
    render(
      <ProgressTimeline
        values={{
          history: [
            { round: 1, score: 0.5 },
            { round: 2, score: 0.7 },
          ],
        }}
        fields={["history"]}
      />,
    );
    const filled = screen.getAllByTestId("timeline-dot-filled");
    const hollow = screen.getAllByTestId("timeline-dot-hollow");
    expect(filled.length).toBe(1);
    expect(hollow.length).toBe(1);
  });
});
```

- [ ] **Step B3.3: Run test to verify failure**

```bash
cd frontend && pnpm test progress-timeline
```

Expected: FAIL — `Cannot find module 'progress-timeline'`.

- [ ] **Step B3.4: Create the ProgressTimeline component**

Create `frontend/src/app/workspace/workflows/[child_thread_id]/_components/progress-timeline.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";

interface Props {
  /** Workflow state values; usually `state.values` from the polled state endpoint. */
  values: Record<string, unknown>;
  /** Spec field names to render as timelines. For demo-flow this is `["history"]`. */
  fields: string[];
}

interface Row {
  fieldName: string;
  index: number;
  isLatest: boolean;
  entry: Record<string, unknown>;
}

/**
 * Vertical timeline panel for non-LLM workflows (option A in the
 * 2026-04-29 design). One row per entry in each timeline field.
 * Fields not on the spec's progress_timeline_fields list are ignored.
 *
 * Returns null if there are no fields and no entries to render.
 */
export function ProgressTimeline({ values, fields }: Props) {
  const listRef = useRef<HTMLDivElement>(null);

  // Collect all rows across all fields, in declaration order, in entry order.
  const rows: Row[] = [];
  for (const f of fields) {
    const arr = values[f];
    if (!Array.isArray(arr)) continue;
    for (let i = 0; i < arr.length; i++) {
      const entry = arr[i];
      if (entry && typeof entry === "object") {
        rows.push({
          fieldName: f,
          index: i,
          isLatest: i === arr.length - 1,
          entry: entry as Record<string, unknown>,
        });
      }
    }
  }

  // Autoscroll to bottom on new row.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows.length]);

  if (fields.length === 0) return null;
  if (rows.length === 0) {
    return (
      <div className="text-muted-foreground border-b p-3 text-center text-sm">
        No progress yet.
      </div>
    );
  }

  return (
    <div className="border-b">
      <div className="text-muted-foreground px-3 pt-2 text-xs uppercase tracking-wide">
        Progress
      </div>
      <div
        ref={listRef}
        className="max-h-[40vh] space-y-1.5 overflow-auto p-3"
      >
        {rows.map((r) => (
          <TimelineRow key={`${r.fieldName}-${r.index}`} row={r} />
        ))}
      </div>
    </div>
  );
}

function TimelineRow({ row }: { row: Row }) {
  const isHint =
    Array.isArray(row.entry.hints) && row.entry.hints.length > 0;
  const segments: string[] = [];
  for (const [k, v] of Object.entries(row.entry)) {
    if (k === "hints") continue;
    segments.push(formatKV(k, v));
  }
  if (isHint) {
    const hints = (row.entry.hints as unknown[]).map(String).join(" / ");
    segments.push(`💬 ${hints}`);
  }

  return (
    <div className="flex items-start gap-2 text-sm">
      <span
        data-testid={
          row.isLatest ? "timeline-dot-filled" : "timeline-dot-hollow"
        }
        className={`mt-1.5 size-2 shrink-0 rounded-full ${
          row.isLatest ? "bg-primary" : "border-muted-foreground border"
        }`}
      />
      <span className="text-foreground/80 flex-1 font-mono text-xs">
        {segments.join(" · ")}
      </span>
    </div>
  );
}

function formatKV(k: string, v: unknown): string {
  if (v === null || v === undefined) return `${k}=∅`;
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
    return `${k}=${v}`;
  }
  // Nested object/array → collapsed JSON
  try {
    return `${k}=${JSON.stringify(v)}`;
  } catch {
    return `${k}=<unserializable>`;
  }
}
```

- [ ] **Step B3.5: Run tests to verify pass**

```bash
cd frontend && pnpm test progress-timeline
```

Expected: all 6 tests pass.

- [ ] **Step B3.6: Run typecheck and lint**

```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: clean.

- [ ] **Step B3.7: Commit**

```bash
git add frontend/src/core/workflows/types.ts \
        frontend/src/app/workspace/workflows/[child_thread_id]/_components/progress-timeline.tsx \
        frontend/tests/unit/components/workspace/workflows/progress-timeline.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): ProgressTimeline component for non-LLM workflows

Vertical timeline list (option A): one row per entry in each spec-
declared progress_timeline_field. Most-recent row gets a filled dot,
older rows hollow. Hint-bearing entries get a 💬 prefix. Nested
objects render as collapsed JSON.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

## Task B4: Wire ProgressTimeline into the detail page

The detail page already passes `WorkflowEntry` into `WorkflowChatPanel`. We'll add the Timeline above the chat panel, sharing the same polled state via the existing `useWorkflowChat` hook (which exposes `progress`).

Wait — `useWorkflowChat` returns `progress: stateQuery.data?.values ?? {}`. That's the full values object, perfect for ProgressTimeline.

But the timeline lives outside ChatPanel (on the page level), so we need either to lift the polling up or to render the timeline inside ChatPanel. Lifting up means duplicate polling (bad). Easiest: render Timeline inside ChatPanel as a header section, conditionally on `workflow.progress_timeline_fields.length > 0`.

**Files:**
- Modify: `frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx` — embed `<ProgressTimeline>`

- [ ] **Step B4.1: Embed ProgressTimeline in ChatPanel**

In `workflow-chat-panel.tsx`, add the import:

```tsx
import { ProgressTimeline } from "./progress-timeline";
```

Then locate the section between the `Header` block and the `Terminal summary card` block (around line 99-100) and insert the timeline:

```tsx
      {/* Header */}
      ...
      </div>

      {/* Progress timeline (only when spec declares fields) */}
      {workflow.progress_timeline_fields &&
        workflow.progress_timeline_fields.length > 0 && (
          <ProgressTimeline
            values={progress}
            fields={workflow.progress_timeline_fields}
          />
        )}

      {/* Terminal summary card */}
      ...
```

`progress` here is the destructured value from the hook. Update the destructure if `progress` isn't already pulled out:

```tsx
  const { messages, isLoading, send, isSending, progress } = useWorkflowChat(
    parentThreadId,
    workflow.child_thread_id,
  );
```

(`progress` should already be there from the hook return type; verify by viewing `use-workflow-chat.ts` and the hook destructure in the panel — fix if missing.)

- [ ] **Step B4.2: Update WorkflowEntry consumer assumption**

Quick check: the page reads `WorkflowEntry` via the hub aggregator response. Since Stage B1+B2 added `progress_timeline_fields` to the API response and types, the data is automatically present. No frontend wiring needed beyond the import + render.

- [ ] **Step B4.3: Run typecheck and lint**

```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: clean.

- [ ] **Step B4.4: Manual smoke**

If gateway is up, navigate to a running demo-flow detail page. Expected:
- A "Progress" section appears between the header and chat area.
- Each `history` entry renders as one row with `round=N · score=0.X`.
- The latest row has a filled blue dot.
- New rows fade in at the bottom every ~2s (poll_wait_node tick).

- [ ] **Step B4.5: Commit**

```bash
git add frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): render ProgressTimeline above chat panel in detail page

Demo-flow declares progress_timeline_fields=["history"]; the panel now
renders a live-updating round/score list, addressing the previous
'detail page is visually static for non-LLM workflows' issue.


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

# Final Verification

- [ ] **Step F1: Backend full suite**

```bash
cd backend && uv run pytest && uv run ruff check .
```

Expected: all pass, clean lint.

- [ ] **Step F2: Frontend full checks**

```bash
cd frontend && pnpm lint && pnpm typecheck && pnpm test
```

Expected: clean.

- [ ] **Step F3: Manual end-to-end smoke**

Bump `poll_wait_node.sleep` to 8s temporarily for visibility (do NOT commit this change).

Walk through:
1. Start demo-flow with `max_rounds=8` from a chat thread.
2. Open detail page.
3. Verify Progress timeline shows rows ticking in (round=1, round=2, ...) every ~8s.
4. Send a hint via the input. Pending bubble appears immediately.
5. Within 1-2 ticks, pending bubble disappears (matched), canonical bubble + ✓✓ appears.
6. Verify a new history row with `💬 your hint text` appears in the timeline at the corresponding round.
7. Wait for completion. Terminal summary appears at top of chat area; report markdown rendered.

Restore `poll_wait_node.sleep` to 2s.

- [ ] **Step F4: Update smoke doc**

Open `docs/superpowers/smoke/2026-04-29-workflow-ui-smoke.md` and:
- Mark Bug 5 as fixed in the bug list (move to "fixed" section, add commit refs).
- Mark D14, D15, D16 as ☑.
- Add a new "L. Progress Timeline" section with checkmarks for the new behaviors.

```bash
git add docs/superpowers/smoke/2026-04-29-workflow-ui-smoke.md
git commit -m "$(cat <<'EOF'
docs(smoke): mark Bug 5 fixed and add Progress Timeline coverage


💘 Generated with Crush


Assisted-by: Claude Sonnet 4.5 via Crush <crush@charm.land>
EOF
)"
```

---

# Self-Review Notes

- **Spec coverage**: Stage A directly addresses Bug 5 (`docs/superpowers/smoke/2026-04-29-workflow-ui-smoke.md` round-2 finding). Stage B addresses the "detail page visually static" finding from this conversation, mapping to "option A: vertical timeline list" the user explicitly approved.
- **Type consistency**: `progress_timeline_fields` is `list[str]` in Python, `string[]` in TS, named identically across boundaries.
- **No placeholders**: every code step has full code; every test has full code; every command has full path.
- **Risks** (call out for reviewer):
  - **R1**: `_BG_TASKS` is process-local. If gateway runs multiple workers, an inject lands on a worker that doesn't own the running task and routes wrongly to terminal-write path. **Mitigation for now**: gateway is single-process by deployment convention (verified: `--reload` only, no `--workers >1` in Makefile). Document the constraint in `emit.py` docstring; revisit if multi-worker is adopted.
  - **R2**: `pendingHints` content-based dedup will collapse duplicate-content sends within poll window. Acceptable for now (human-paced UI); revisit if rapid bursts become common.
  - **R3**: Stage A's regression test starts a real running workflow on SQLite which makes it slower (~5-10s). It's marked async + uses `wait_for(20)`; acceptable for CI.
- **Self-audit pass**: re-read Stage A — confirms the new code in `work_loop_node` correctly merges `new_inbox_msgs` into both `update["messages"]` (via add_messages reducer) AND the `_seen_msg_ids` deduplication (since `candidate_msgs = list(msgs) + new_inbox_msgs` covers them). Confirmed `inject_user_message_to_workflow` uses lazy import to avoid the known `tools <-> emit` cycle.

---

# Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-29-workflow-detail-page-fixes.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review

Which approach?
