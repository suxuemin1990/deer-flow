# Workflow UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing chat-page `ActiveWorkflowsPanel` with a top-level Workflow Hub (list + detail routes) and migrate workflow injection from the in-process `hints_inbox` to each workflow's own LangGraph `messages` channel, enabling a true bidirectional chat between users and running workflows.

**Architecture:** Each opted-in workflow's state schema gains a `messages: Annotated[list, add_messages]` field; user injection (UI or `inject_hint` tool) appends a `HumanMessage` via `aupdate_state`; workflow nodes consume new `HumanMessage`s through their existing inner LLM and may append `AIMessage` replies. A new `/workspace/workflows` route surfaces a tree (parent threads → workflows) and per-workflow detail at `/workspace/workflows/<child_thread_id>`. The lead agent's `start_workflow` tool message carries both a text guidance string and a structured `additional_kwargs.element="workflow_link"` payload so the chat UI can render a clickable card. The legacy `ActiveWorkflowsPanel`, red-dot mechanism, and `hints_inbox` module are removed.

**Tech Stack:** Python 3.12 (FastAPI gateway, LangGraph), Next.js 16 + React 19 + TypeScript (frontend), pytest + ruff (backend tests/lint), Vitest + tsc + eslint (frontend tests/lint).

**Reference spec:** `docs/superpowers/specs/2026-04-29-workflow-ui-redesign-design.md`.

---

## Stages

The plan is organised into 5 stages matching the spec's Migration section. Each stage produces working software:

1. **Backend foundation** — schema/tool changes, `messages` channel adoption, `hints_inbox` removal.
2. **Backend hub API** — new `POST .../messages` and `GET /workflows/all` endpoints.
3. **Frontend hub list + detail routes** — new `/workspace/workflows` UX.
4. **Lead-agent guidance** — structured `workflow_link` in tool message + frontend card renderer.
5. **Old UX removal** — delete `ActiveWorkflowsPanel`, `hasUnreadFinish` red-dot, related stores.

Each stage builds on the previous; stage N tests must pass before starting stage N+1.

---

## Stage 1: Backend Foundation

### Task 1.1: Extend `WorkflowSpec` with `accepts_chat`

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/registry.py`
- Test: `backend/tests/test_workflows_registry.py` (existing)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflows_registry.py`:

```python
def test_workflow_spec_accepts_chat_defaults_false():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "demo",
        "description": "x",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    spec = reg.get("demo")
    assert spec.accepts_chat is False


def test_workflow_spec_accepts_chat_explicit_true():
    from deerflow.workflows.registry import WorkflowRegistry

    items = [{
        "name": "demo",
        "description": "x",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
        "accepts_chat": True,
    }]
    reg = WorkflowRegistry.load_from_dicts(items)
    assert reg.get("demo").accepts_chat is True
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_workflows_registry.py::test_workflow_spec_accepts_chat_defaults_false -v`
Expected: FAIL with `AttributeError: 'WorkflowSpec' object has no attribute 'accepts_chat'`

- [ ] **Step 3: Add `accepts_chat` to dataclass and loader**

In `backend/packages/harness/deerflow/workflows/registry.py`, add to `WorkflowSpec`:

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
    hint_behavior_doc: str = ""
    accepts_chat: bool = False
```

In `load_from_dicts`, inside the `WorkflowSpec(...)` construction:

```python
specs.append(WorkflowSpec(
    name=item["name"],
    description=item["description"],
    factory=factory,
    input_schema=input_schema,
    done_field=item["done_field"],
    report_field=item["report_field"],
    progress_fields=list(item.get("progress_fields") or []),
    hint_behavior_doc=item.get("hint_behavior_doc") or "",
    accepts_chat=bool(item.get("accepts_chat", False)),
))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_workflows_registry.py -v`
Expected: PASS (both new tests + any existing tests still passing)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/registry.py backend/tests/test_workflows_registry.py
git commit -m "feat(workflows): add accepts_chat flag to WorkflowSpec"
```

---

### Task 1.2: Add `messages` channel helpers — write HumanMessage to child thread

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/emit.py`
- Test: `backend/tests/test_workflows_inject_message.py` (new)

The existing `emit_to_parent_thread` writes an `AIMessage` to the parent. The new `inject_user_message_to_workflow` writes a `HumanMessage` to the child. Both share the same `_build_message_appender` infrastructure.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflows_inject_message.py`:

```python
"""Tests for inject_user_message_to_workflow — append HumanMessage to a
running workflow's messages channel."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_inject_user_message_appends_human_message_to_child_thread():
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    child_tid = "child-1"

    await inject_user_message_to_workflow(
        child_tid, "use dropout", checkpointer=cp,
    )

    # Verify the HumanMessage landed in the child thread's messages channel.
    from deerflow.workflows.emit import _build_message_appender
    appender = _build_message_appender(cp)
    state = await appender.aget_state({"configurable": {"thread_id": child_tid}})
    msgs = state.values.get("messages") or []
    assert len(msgs) == 1
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "use dropout"


@pytest.mark.asyncio
async def test_inject_user_message_appends_to_existing_messages():
    from deerflow.workflows.emit import (
        _build_message_appender,
        inject_user_message_to_workflow,
    )

    cp = MemorySaver()
    child_tid = "child-2"

    appender = _build_message_appender(cp)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": child_tid}},
        values={"messages": [AIMessage(content="hello")]},
    )

    await inject_user_message_to_workflow(child_tid, "ok", checkpointer=cp)

    state = await appender.aget_state({"configurable": {"thread_id": child_tid}})
    msgs = state.values.get("messages") or []
    assert len(msgs) == 2
    assert isinstance(msgs[0], AIMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert msgs[1].content == "ok"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && uv run pytest tests/test_workflows_inject_message.py -v`
Expected: FAIL with `ImportError: cannot import name 'inject_user_message_to_workflow'`

- [ ] **Step 3: Implement helper**

In `backend/packages/harness/deerflow/workflows/emit.py`, add at the bottom:

```python
async def inject_user_message_to_workflow(
    child_thread_id: str,
    content: str,
    *,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Append a HumanMessage to a workflow child thread's messages channel.

    Mirrors :func:`emit_to_parent_thread` but writes HumanMessage (user
    injection) into the *child* thread instead of AIMessage (agent reply)
    into the parent. Workflow nodes consume new HumanMessages by reading
    ``state["messages"]`` at the start of each tick.

    Note:
        Requires the workflow's state schema to declare a ``messages``
        channel with the ``add_messages`` reducer; otherwise the field is
        silently dropped by the checkpointer (sqlite). Specs that should
        accept chat injection must set ``accepts_chat=True`` and define
        ``messages`` in their TypedDict.
    """
    from langchain_core.messages import HumanMessage

    appender = _build_message_appender(checkpointer)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": child_thread_id}},
        values={"messages": [HumanMessage(content=content)]},
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_workflows_inject_message.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/emit.py backend/tests/test_workflows_inject_message.py
git commit -m "feat(workflows): inject_user_message_to_workflow writes HumanMessage to child thread"
```

---

### Task 1.3: Update `WorkflowBaseState` doc + provide opt-in `messages` mixin

The `messages` channel is opt-in per workflow (per the `accepts_chat` flag). We document the contract on `WorkflowBaseState` but do not force-add the field, since legacy specs may want to stay on the no-chat schema.

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/base_state.py`
- Test: `backend/tests/test_workflow_base_state_chat_mixin.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_base_state_chat_mixin.py`:

```python
"""WorkflowChatStateMixin contributes a `messages` add_messages channel."""

from __future__ import annotations

from typing import get_type_hints


def test_workflow_chat_state_mixin_declares_messages_channel():
    from deerflow.workflows.base_state import WorkflowChatStateMixin

    hints = get_type_hints(WorkflowChatStateMixin, include_extras=True)
    assert "messages" in hints, (
        "WorkflowChatStateMixin must declare a `messages` channel that "
        "workflows opting into chat compose into their state."
    )


def test_workflow_chat_state_mixin_uses_add_messages_reducer():
    """The `messages` annotation must include the langgraph add_messages reducer."""
    from typing import get_args

    from langgraph.graph.message import add_messages

    from deerflow.workflows.base_state import WorkflowChatStateMixin

    hints = get_type_hints(WorkflowChatStateMixin, include_extras=True)
    annotated = hints["messages"]
    args = get_args(annotated)
    assert add_messages in args, (
        f"messages annotation must include add_messages reducer, got {args!r}"
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && uv run pytest tests/test_workflow_base_state_chat_mixin.py -v`
Expected: FAIL with `ImportError: cannot import name 'WorkflowChatStateMixin'`

- [ ] **Step 3: Add mixin and update doc**

Replace the contents of `backend/packages/harness/deerflow/workflows/base_state.py`:

```python
"""Platform-reserved fields every workflow's state must carry.

Workflows compose this with their own business fields::

    class MyFlowState(WorkflowBaseState):
        task_name: str
        max_rounds: int
        ...

The platform reads ``_parent_thread_id`` (set by start_workflow tool) and
``_error`` (set by background runner on exception).

**Bidirectional chat (opt-in):** workflows that want to receive user
injection through the UI / inject_hint tool, and reply with AIMessages,
should additionally compose :class:`WorkflowChatStateMixin`::

    class MyFlowState(WorkflowBaseState, WorkflowChatStateMixin):
        ...

and the corresponding spec must declare ``accepts_chat: True``. New
HumanMessages are appended to ``messages`` by the platform; workflow
nodes are expected to filter by ``_seen_msg_ids`` (which they own and
update themselves) to avoid re-feeding the inner LLM on every tick.

Hints **no longer** flow through ``hints_inbox`` (deleted as of the
2026-04-29 redesign). All injection is via the ``messages`` channel.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class WorkflowBaseState(TypedDict, total=False):
    _parent_thread_id: str
    _error: str


class WorkflowChatStateMixin(TypedDict, total=False):
    """Opt-in mixin for workflows that accept user-injected chat messages.

    ``messages``: bidirectional chat history. HumanMessages come from
        user injection; AIMessages come from workflow nodes' returns.
    ``_seen_msg_ids``: workflow-author-owned set of message ids already
        consumed; used to avoid re-feeding the same hint into the inner
        LLM each tick. The framework neither writes nor reads this.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    _seen_msg_ids: set[str]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_workflow_base_state_chat_mixin.py tests/test_workflows_inject_message.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/base_state.py backend/tests/test_workflow_base_state_chat_mixin.py
git commit -m "feat(workflows): WorkflowChatStateMixin declares opt-in messages channel"
```

---

### Task 1.4: Migrate `demo_flow` to use `WorkflowChatStateMixin`

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/demo_flow/state.py`
- Modify: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py`
- Modify: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/final_node.py`
- Modify: `config.example.yaml` (workflow yaml entry)
- Test: `backend/tests/test_demo_flow_messages_channel.py` (new)

This is the canary migration; if it works, real workflows can follow the same pattern.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_demo_flow_messages_channel.py`:

```python
"""Demo flow consumes new HumanMessages through state['messages']."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_demo_flow_records_injected_human_message_in_history():
    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    graph = make_graph(checkpointer=cp)
    child_tid = "child-demo"
    config = {"configurable": {"thread_id": child_tid}}

    # Inject a user message before running
    await inject_user_message_to_workflow(
        child_tid, "use dropout", checkpointer=cp,
    )

    # Run demo flow
    final = await graph.ainvoke(
        {"task_name": "t", "max_rounds": 1, "_parent_thread_id": "p"},
        config=config,
    )

    history = final.get("history") or []
    # The hint must be reflected somewhere in history (work_loop_node should
    # have observed the new HumanMessage and stamped it into history).
    hint_entries = [e for e in history if "hints" in e]
    assert hint_entries, f"expected at least one hint entry, got history={history!r}"
    seen = sum((e.get("hints") or []) for e in hint_entries), []
    seen_flat = [t for sublist in seen if isinstance(sublist, list) for t in sublist]
    assert any("dropout" in (h or "") for h in seen_flat), (
        f"expected 'dropout' to appear in recorded hints; got {seen_flat!r}"
    )


@pytest.mark.asyncio
async def test_demo_flow_seen_msg_ids_prevents_double_processing():
    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = MemorySaver()
    graph = make_graph(checkpointer=cp)
    child_tid = "child-demo-2"
    config = {"configurable": {"thread_id": child_tid}}

    await inject_user_message_to_workflow(
        child_tid, "first hint", checkpointer=cp,
    )

    final = await graph.ainvoke(
        {"task_name": "t", "max_rounds": 2, "_parent_thread_id": "p"},
        config=config,
    )

    history = final.get("history") or []
    hint_entries = [e for e in history if "hints" in e]
    # The hint should be recorded exactly once across both rounds (not
    # re-processed on the second round).
    flat = [h for e in hint_entries for h in (e.get("hints") or [])]
    assert flat.count("first hint") == 1, (
        f"hint should be processed exactly once across rounds; got {flat!r}"
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && uv run pytest tests/test_demo_flow_messages_channel.py -v`
Expected: FAIL — current demo_flow uses `hints_inbox.pop_hints`, not `state["messages"]`.

- [ ] **Step 3: Update `state.py`**

Replace contents of `backend/packages/harness/deerflow/workflows/demo_flow/state.py`:

```python
"""DemoFlow state (English field names; inherits platform reserved fields)."""

from __future__ import annotations

from typing import Annotated, NotRequired

from deerflow.workflows.base_state import WorkflowBaseState, WorkflowChatStateMixin


def _merge_list(existing: list | None, new: list | None) -> list:
    if existing is None:
        return new or []
    if new is None:
        return existing
    return existing + new


class DemoFlowState(WorkflowBaseState, WorkflowChatStateMixin):
    task_name: str
    max_rounds: int
    current_round: NotRequired[int]
    history: Annotated[list[dict], _merge_list]
    report_markdown: NotRequired[str]
    is_done: NotRequired[bool]
```

- [ ] **Step 4: Update `work_loop_node.py`**

Replace contents of `backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py`:

```python
"""Increment round counter; consume any new injected HumanMessages.

Hints arrive via the workflow's ``messages`` channel (populated by user
injection in the Workflow Hub UI or by the lead agent's ``inject_hint``
tool). On each tick we filter ``state['messages']`` for HumanMessages
whose id is not yet in ``state['_seen_msg_ids']``, stamp their content
into ``history``, and update the seen-set.

Demo_flow does nothing semantic with hints — it only proves the
messages-channel delivery pipe works end-to-end. Real workflows should
feed the new HumanMessages into their inner LLM and let the LLM react.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig


async def work_loop_node(state, config: RunnableConfig):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}

    update: dict = {"current_round": current + 1, "is_done": False}

    seen = state.get("_seen_msg_ids") or set()
    msgs = state.get("messages") or []
    new_human_msgs = [
        m for m in msgs
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

- [ ] **Step 5: Update `final_node.py` doc**

Edit `backend/packages/harness/deerflow/workflows/demo_flow/nodes/final_node.py`, replace the module docstring (top 7 lines):

```python
"""Render markdown report from accumulated history.

History entries are heterogeneous: ``{"round", "score"}`` (one per round
from poll_wait_node) plus optional ``{"round", "hints": [...]}`` entries
contributed by work_loop_node when injected HumanMessages land mid-run.
The report only tables score-bearing entries; non-scored entries are
filtered out.
"""
```

The function body is unchanged.

- [ ] **Step 6: Update `config.example.yaml`**

Find the `demo-flow` block in `config.example.yaml` (around line 985) and replace its `hint_behavior_doc` and add `accepts_chat`:

```yaml
  - name: demo-flow
    description: |
      Zero-LLM demo pipeline used to validate the workflow platform end-to-end.
      Pretends to run training rounds and produces a small markdown report.
      Useful for testing workflow chat injection / cancel_workflow /
      get_workflow_progress without spending real model tokens.
    factory: deerflow.workflows.demo_flow:make_graph
    input_schema: deerflow.workflows.demo_flow:DemoFlowInput
    done_field: is_done
    report_field: report_markdown
    progress_fields: [current_round, max_rounds, history]
    accepts_chat: true
    hint_behavior_doc: |
      Demo-only — work_loop_node consumes new HumanMessages from the
      messages channel and stamps their content into history. The graph
      has no LLM nodes, so it does not produce AIMessage replies; the
      Workflow Hub UI surfaces ✓ (delivered) and ✓✓ (consumed, when
      progress fields advance).
```

- [ ] **Step 7: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_demo_flow_messages_channel.py tests/test_workflows_inject_message.py -v`
Expected: PASS

- [ ] **Step 8: Run wider suite to check no regression**

Run: `cd backend && uv run pytest tests/ -k "demo_flow or workflow" -v`
Expected: PASS (some existing tests for demo_flow may rely on the old `pop_hints` path — see Task 1.5 for those)

- [ ] **Step 9: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/demo_flow/ \
        backend/tests/test_demo_flow_messages_channel.py \
        config.example.yaml
git commit -m "feat(demo_flow): consume hints via messages channel + accepts_chat=true"
```

---

### Task 1.5: Rewrite `inject_hint` tool to use `messages` channel

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/tools.py`
- Test: `backend/tests/test_workflows_tools.py` (existing — adjust)

The tool's signature and LLM-facing description stay the same. Internally it switches from `push_hint` to `inject_user_message_to_workflow`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflows_tools.py`:

```python
@pytest.mark.asyncio
async def test_inject_hint_writes_human_message_via_messages_channel(monkeypatch):
    """inject_hint must call inject_user_message_to_workflow, not push_hint."""
    import deerflow.workflows.tools as wftools
    from deerflow.workflows.tools import inject_hint

    monkeypatch.setattr(
        wftools, "_THREAD_TO_WORKFLOW", {"c": "demo-flow"}, raising=False,
    )

    captured: dict = {}
    async def fake_inject(child_tid, content, *, checkpointer):
        captured["child_tid"] = child_tid
        captured["content"] = content

    import deerflow.workflows.emit as emit_mod
    monkeypatch.setattr(emit_mod, "inject_user_message_to_workflow", fake_inject)

    # Also stub get_default_checkpointer so the tool's import succeeds
    import deerflow.runtime.checkpointer_singleton as cs
    monkeypatch.setattr(cs, "get_default_checkpointer", lambda: object())

    result = await inject_hint.ainvoke({
        "thread_id": "c",
        "hint": "use dropout",
        "tool_call_id": "tc-1",
    })

    assert captured == {"child_tid": "c", "content": "use dropout"}
    # Verify return Command still has a ToolMessage
    msg = result.update["messages"][0]
    assert "demo-flow" in msg.content
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_workflows_tools.py::test_inject_hint_writes_human_message_via_messages_channel -v`
Expected: FAIL — current implementation calls `push_hint`, not `inject_user_message_to_workflow`.

- [ ] **Step 3: Rewrite `inject_hint` body**

In `backend/packages/harness/deerflow/workflows/tools.py`, replace the `inject_hint` function body (lines ~131-163):

```python
@tool
async def inject_hint(
    thread_id: str,
    hint: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Inject a free-text instruction into a running workflow's chat channel.

    The hint is appended to the workflow's ``messages`` channel as a
    HumanMessage. Workflow nodes consume it on their next tick (typically
    by feeding it into their inner LLM, which decides how to react).
    Workflows that do not declare ``accepts_chat=True`` will silently drop
    the message.

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
    from deerflow.workflows.emit import inject_user_message_to_workflow

    cp = get_default_checkpointer()
    await inject_user_message_to_workflow(thread_id, hint, checkpointer=cp)
    return _tool_msg(f"Hint injected into {name!r} (thread_id={thread_id}).", tool_call_id)
```

Also update `get_workflow_progress` to no longer reference `peek_hints` — replace lines ~220-228 (the `from deerflow.workflows.hints_inbox import peek_hints` block and the `_hints` payload key):

```python
    payload: dict[str, Any] = {
        "workflow": name,
        "thread_id": thread_id,
        spec.done_field: values.get(spec.done_field, False),
        "_error": values.get("_error"),
    }
```

(The `_hints` key is dropped from the payload — workflow progress is now visible via the messages channel directly. LLM tools wanting to see chat history can read the child's state via `/threads/{c}/state`, but `get_workflow_progress` stays focused on progress_fields.)

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && uv run pytest tests/test_workflows_tools.py -v`
Expected: PASS (new test plus existing tests; some existing tests for `inject_hint` and `get_workflow_progress` may need to be updated — fix them as failures surface, removing references to `hints_inbox` / `_hints` / `pop_hints`)

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/tools.py backend/tests/test_workflows_tools.py
git commit -m "feat(workflows): inject_hint writes through messages channel"
```

---

### Task 1.6: Delete `hints_inbox.py`

**Files:**
- Delete: `backend/packages/harness/deerflow/workflows/hints_inbox.py`
- Modify: any remaining importers (audit + remove imports)
- Delete: any tests asserting on `hints_inbox` directly

- [ ] **Step 1: Audit remaining importers**

Run:
```bash
grep -rn "hints_inbox\|pop_hints\|push_hint\|peek_hints\|reset_inbox" backend/ \
  --include="*.py" --exclude-dir=__pycache__ --exclude-dir=.venv
```

Expected hits at this point: only test files referencing the now-removed module. Note each file in a list to remove or rewrite.

- [ ] **Step 2: Write the failing test (regression: module gone)**

Create `backend/tests/test_hints_inbox_removed.py`:

```python
"""hints_inbox.py was deleted in the 2026-04-29 redesign — guard against revival."""

import pytest


def test_hints_inbox_module_does_not_exist():
    with pytest.raises(ImportError):
        import deerflow.workflows.hints_inbox  # noqa: F401
```

- [ ] **Step 3: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_hints_inbox_removed.py -v`
Expected: FAIL — module still imports successfully (we haven't deleted it yet).

- [ ] **Step 4: Delete `hints_inbox.py` and clean up importers**

```bash
rm backend/packages/harness/deerflow/workflows/hints_inbox.py
```

For each file the audit step found:
- If it's a test file specifically about the inbox (e.g. `test_hints_inbox.py`), `git rm` it.
- If it's any other file with a stale import, remove the import line.

Likely targets to inspect/clean:
- `backend/tests/test_hints_inbox.py` (if it exists) — `git rm`
- Any remaining `from deerflow.workflows.hints_inbox import ...` in tests covered by 1.5 — should already be cleaned, but re-check.

- [ ] **Step 5: Run test to verify pass + run full workflow tests**

Run: `cd backend && uv run pytest tests/test_hints_inbox_removed.py tests/ -k workflow -v`
Expected: PASS for all.

- [ ] **Step 6: Commit**

```bash
git add -A backend/packages/harness/deerflow/workflows/ backend/tests/
git commit -m "feat(workflows): delete hints_inbox; messages channel is the only injection path"
```

---

### Task 1.7: Stage 1 verification

- [ ] **Step 1: Run full backend test suite + lint**

Run: `cd backend && uv run pytest 2>&1 | tail -10 && uv run ruff check .`

Expected:
- All tests pass.
- Ruff: only pre-existing errors in `packages/harness/deerflow/agents/training_explore/` (unrelated, untracked work-in-progress; do NOT fix as part of this plan). Any new errors in files we touched must be fixed.

- [ ] **Step 2: If any new lint errors in touched files, fix them and re-run**

Touched files in stage 1:
- `backend/packages/harness/deerflow/workflows/registry.py`
- `backend/packages/harness/deerflow/workflows/emit.py`
- `backend/packages/harness/deerflow/workflows/base_state.py`
- `backend/packages/harness/deerflow/workflows/demo_flow/state.py`
- `backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py`
- `backend/packages/harness/deerflow/workflows/demo_flow/nodes/final_node.py`
- `backend/packages/harness/deerflow/workflows/tools.py`

Run `uv run ruff check <each file>` and apply fixes if any.

- [ ] **Step 3: Stage 1 commit gate**

If any unstaged changes from lint fixes exist:

```bash
git add -A backend/
git commit -m "chore(workflows): stage 1 lint cleanup"
```

---

## Stage 2: Backend Hub API

### Task 2.1: `POST /api/threads/{p}/workflows/{c}/messages`

**Files:**
- Modify: `backend/app/gateway/routers/threads.py`
- Test: `backend/tests/test_threads_workflow_messages_endpoint.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_threads_workflow_messages_endpoint.py`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_threads_workflow_messages_endpoint.py -v`
Expected: FAIL with `ImportError: cannot import name 'post_workflow_message'`.

- [ ] **Step 3: Implement endpoint**

In `backend/app/gateway/routers/threads.py`, add a body model near the top with the others:

```python
class WorkflowMessageBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
```

Add the endpoint right after `cancel_active_workflow` (around line 747):

```python
@router.post("/{thread_id}/workflows/{child_id}/messages")
async def post_workflow_message(
    thread_id: str,
    child_id: str,
    body: WorkflowMessageBody,
    request: Request,
) -> dict:
    """Append a HumanMessage to a workflow child thread's messages channel.

    User-driven injection from the Workflow Hub UI. Mirrors the
    ``inject_hint`` tool's effect — both write through the same helper.
    Returns 404 if ``child_id`` is not a platform-registered workflow
    thread; the parent ``thread_id`` is currently informational (kept in
    the URL for future per-parent authorization checks).
    """
    from deerflow.workflows.emit import inject_user_message_to_workflow
    from deerflow.workflows.tools import _THREAD_TO_WORKFLOW

    if child_id not in _THREAD_TO_WORKFLOW:
        raise HTTPException(
            status_code=404,
            detail=f"child_id={child_id!r} is not a registered workflow thread",
        )
    cp = get_checkpointer(request)
    await inject_user_message_to_workflow(child_id, body.content, checkpointer=cp)
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd backend && uv run pytest tests/test_threads_workflow_messages_endpoint.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/threads.py backend/tests/test_threads_workflow_messages_endpoint.py
git commit -m "feat(api): POST /threads/{p}/workflows/{c}/messages — UI-direct injection"
```

---

### Task 2.2: `GET /api/workflows/all` — cross-thread aggregation

**Files:**
- Create: `backend/app/gateway/routers/workflows_hub.py`
- Modify: `backend/app/gateway/__init__.py` or wherever routers are registered (auto-discover via grep)
- Test: `backend/tests/test_workflows_hub_endpoint.py` (new)

This endpoint walks all threads in the Store, filters those with non-empty `metadata.child_workflow_threads`, classifies each child's status from its checkpoint, and returns a denormalized parent→workflows tree.

- [ ] **Step 1: Find the router registration point**

Run:
```bash
grep -rn "include_router\|threads_router\|app.gateway.routers" backend/app/gateway/ --include="*.py"
```

Note the file (likely `backend/app/gateway/main.py` or `backend/app/gateway/__init__.py`). The new router will be added the same way.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_workflows_hub_endpoint.py`:

```python
"""Tests for GET /api/workflows/all — cross-thread workflow aggregation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_workflows_hub_returns_parents_with_their_children():
    """A parent thread with two child workflows shows both in the tree."""
    from app.gateway.routers.workflows_hub import list_all_workflows

    # Build a fake Store + Checkpointer
    store = MagicMock()
    parent_record = {
        "thread_id": "p1",
        "title": "Discussion about training",
        "created_at": "2026-04-29T10:00:00+00:00",
        "metadata": {
            "child_workflow_threads": [
                {"thread_id": "c1", "name": "demo-flow",
                 "started_at": "2026-04-29T10:05:00+00:00"},
                {"thread_id": "c2", "name": "demo-flow",
                 "started_at": "2026-04-29T10:10:00+00:00"},
            ],
        },
    }
    item = MagicMock()
    item.value = parent_record
    item.key = "p1"
    store.asearch = AsyncMock(return_value=[item])

    # Checkpointer returns terminal state for c1, in-progress for c2
    cp = MagicMock()

    def make_tuple(values):
        t = MagicMock()
        t.checkpoint = {"channel_values": values}
        return t

    async def aget_tuple(config):
        cid = config["configurable"]["thread_id"]
        if cid == "c1":
            return make_tuple({
                "is_done": True, "current_round": 3, "max_rounds": 3,
                "report_markdown": "## Report\n...",
            })
        if cid == "c2":
            return make_tuple({
                "is_done": False, "current_round": 1, "max_rounds": 3,
            })
        return None

    cp.aget_tuple = AsyncMock(side_effect=aget_tuple)

    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = cp

    # Stub registry so demo-flow is known with progress_fields
    import deerflow.workflows.tools as wftools
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class _IS(BaseModel):
        pass

    spec = WorkflowSpec(
        name="demo-flow", description="x",
        factory=lambda **k: None, input_schema=_IS,
        done_field="is_done", report_field="report_markdown",
        progress_fields=["current_round", "max_rounds"],
    )
    fake_reg = WorkflowRegistry([spec], [])
    wftools._REGISTRY = fake_reg
    # Mark both as registered so they're recognized
    wftools._THREAD_TO_WORKFLOW = {"c1": "demo-flow", "c2": "demo-flow"}

    result = await list_all_workflows(req)

    assert "parents" in result
    assert len(result["parents"]) == 1
    parent = result["parents"][0]
    assert parent["thread_id"] == "p1"
    assert parent["title"] == "Discussion about training"
    assert len(parent["workflows"]) == 2

    by_id = {w["child_thread_id"]: w for w in parent["workflows"]}
    assert by_id["c1"]["status"] == "done"
    assert by_id["c1"]["report_preview"].startswith("## Report")
    assert by_id["c2"]["status"] == "running"
    assert by_id["c2"]["progress"] == {"current_round": 1, "max_rounds": 3}


@pytest.mark.asyncio
async def test_workflows_hub_skips_parents_without_workflows():
    from app.gateway.routers.workflows_hub import list_all_workflows

    store = MagicMock()
    no_workflow_parent = MagicMock()
    no_workflow_parent.value = {
        "thread_id": "px", "title": "regular chat",
        "created_at": "2026-04-29T09:00:00+00:00",
        "metadata": {},
    }
    store.asearch = AsyncMock(return_value=[no_workflow_parent])

    cp = MagicMock()
    cp.aget_tuple = AsyncMock(return_value=None)

    req = MagicMock()
    req.app.state.store = store
    req.app.state.checkpointer = cp

    result = await list_all_workflows(req)
    assert result == {"parents": []}


@pytest.mark.asyncio
async def test_workflows_hub_classifies_failed_and_cancelled():
    """A child whose state contains _error is classified failed; if the
    error string starts with 'CancelledError', it's classified cancelled."""
    from app.gateway.routers.workflows_hub import list_all_workflows

    store = MagicMock()
    parent_record = {
        "thread_id": "p1", "title": "T",
        "created_at": "2026-04-29T10:00:00+00:00",
        "metadata": {"child_workflow_threads": [
            {"thread_id": "c-fail", "name": "demo-flow",
             "started_at": "2026-04-29T10:05:00+00:00"},
            {"thread_id": "c-cancel", "name": "demo-flow",
             "started_at": "2026-04-29T10:06:00+00:00"},
        ]},
    }
    item = MagicMock(); item.value = parent_record; item.key = "p1"
    store.asearch = AsyncMock(return_value=[item])

    def make_tuple(values):
        t = MagicMock(); t.checkpoint = {"channel_values": values}; return t

    async def aget_tuple(config):
        cid = config["configurable"]["thread_id"]
        if cid == "c-fail":
            return make_tuple({"is_done": True, "_error": "RuntimeError: boom"})
        if cid == "c-cancel":
            return make_tuple({
                "is_done": True,
                "_error": "CancelledError: workflow cancelled by user",
            })
        return None
    cp = MagicMock(); cp.aget_tuple = AsyncMock(side_effect=aget_tuple)

    req = MagicMock(); req.app.state.store = store; req.app.state.checkpointer = cp

    import deerflow.workflows.tools as wftools
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class _IS(BaseModel): pass
    spec = WorkflowSpec(
        name="demo-flow", description="x", factory=lambda **k: None,
        input_schema=_IS, done_field="is_done", report_field="report_markdown",
        progress_fields=[],
    )
    wftools._REGISTRY = WorkflowRegistry([spec], [])
    wftools._THREAD_TO_WORKFLOW = {
        "c-fail": "demo-flow", "c-cancel": "demo-flow",
    }

    result = await list_all_workflows(req)
    by_id = {w["child_thread_id"]: w
             for w in result["parents"][0]["workflows"]}
    assert by_id["c-fail"]["status"] == "failed"
    assert "RuntimeError" in by_id["c-fail"]["error"]
    assert by_id["c-cancel"]["status"] == "cancelled"
```

- [ ] **Step 3: Run tests to verify failure**

Run: `cd backend && uv run pytest tests/test_workflows_hub_endpoint.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_all_workflows'`.

- [ ] **Step 4: Implement `workflows_hub.py`**

Create `backend/app/gateway/routers/workflows_hub.py`:

```python
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

router = APIRouter(prefix="/workflows", tags=["workflows-hub"])

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
    from deerflow.workflows.tools import _THREAD_TO_WORKFLOW, _get_registry

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
                "report_preview": _truncate(report, _REPORT_PREVIEW_LEN),
                "error": _truncate(error, _ERROR_PREVIEW_LEN),
            })

        if not wf_entries:
            continue

        parents_out.append({
            "thread_id": parent_thread_id,
            "title": record.get("title") or record.get("metadata", {}).get("title"),
            "created_at": record.get("created_at"),
            "workflows": wf_entries,
        })

    # Sort parents by created_at desc (Q1=b)
    parents_out.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return {"parents": parents_out}
```

- [ ] **Step 5: Register the router**

Find the gateway's router registration (from Step 1's grep). Add an import and `include_router` call following the existing pattern. Likely something like:

```python
from app.gateway.routers.workflows_hub import router as workflows_hub_router

app.include_router(workflows_hub_router, prefix="/api")
```

- [ ] **Step 6: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_workflows_hub_endpoint.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Smoke-test the registered route**

Run: `cd backend && uv run pytest tests/ -k "gateway and (route or routes or include)" -v`
Expected: any existing route-discovery tests still pass and the new route is reachable. If there's no such test, add one quickly:

Append to `backend/tests/test_workflows_hub_endpoint.py`:

```python
@pytest.mark.asyncio
async def test_workflows_hub_route_registered():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.routers.workflows_hub import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    # Without proper deps the endpoint will 500 — we only check it exists.
    r = client.get("/api/workflows/all")
    assert r.status_code in (200, 500), r.status_code
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/gateway/routers/workflows_hub.py \
        backend/tests/test_workflows_hub_endpoint.py
# Add the file you modified to register the router (its path may vary):
git add backend/app/gateway/  # whatever __init__.py / main.py was edited
git commit -m "feat(api): GET /api/workflows/all — cross-thread workflow aggregation"
```

---

### Task 2.3: Stage 2 verification

- [ ] **Step 1: Full backend tests + lint**

Run: `cd backend && uv run pytest 2>&1 | tail -10 && uv run ruff check app/ packages/harness/deerflow/workflows/`

Expected: all tests pass; no new lint errors in `app/gateway/routers/workflows_hub.py` or `app/gateway/routers/threads.py`.

- [ ] **Step 2: Manual smoke (optional but recommended)**

```bash
cd backend && uv run uvicorn app.gateway.main:app --port 8001 &
sleep 3
curl -s http://localhost:8001/api/workflows/all | python -m json.tool
kill %1
```

Expected: JSON `{"parents": []}` (no workflows started yet, but endpoint reachable).

---

## Stage 3: Frontend Hub List + Detail Routes

### Task 3.1: Extend frontend workflow types + API client

**Files:**
- Modify: `frontend/src/core/workflows/types.ts`
- Modify: `frontend/src/core/workflows/api.ts`
- Test: (no unit tests — types are checked by tsc; API functions tested by integration)

- [ ] **Step 1: Add new types**

Append to `frontend/src/core/workflows/types.ts`:

```ts
export type WorkflowStatus = "running" | "done" | "failed" | "cancelled";

export interface WorkflowEntry {
  child_thread_id: string;
  name: string;
  status: WorkflowStatus;
  started_at: string | null;
  finished_at: string | null;
  progress: Record<string, unknown>;
  report_preview: string | null;
  error: string | null;
}

export interface WorkflowParentGroup {
  thread_id: string;
  title: string | null;
  created_at: string;
  workflows: WorkflowEntry[];
}

export interface AllWorkflowsResponse {
  parents: WorkflowParentGroup[];
}

export interface PostWorkflowMessageBody {
  content: string;
}
```

- [ ] **Step 2: Add API functions**

Append to `frontend/src/core/workflows/api.ts`:

```ts
import { getBackendBaseURL } from "../utils/get-backend-base-url";

import type { AllWorkflowsResponse, PostWorkflowMessageBody } from "./types";

export async function fetchAllWorkflows(
  signal?: AbortSignal,
): Promise<AllWorkflowsResponse> {
  const url = `${getBackendBaseURL()}/api/workflows/all`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`fetchAllWorkflows: HTTP ${response.status}`);
  }
  return (await response.json()) as AllWorkflowsResponse;
}

export async function postWorkflowMessage(
  parentThreadId: string,
  childThreadId: string,
  body: PostWorkflowMessageBody,
): Promise<{ ok: true }> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    parentThreadId,
  )}/workflows/${encodeURIComponent(childThreadId)}/messages`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`postWorkflowMessage: HTTP ${response.status}`);
  }
  return (await response.json()) as { ok: true };
}
```

(The existing top of `api.ts` already imports `getBackendBaseURL`; do NOT duplicate the import — merge into the existing import line if present.)

- [ ] **Step 3: typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/workflows/types.ts frontend/src/core/workflows/api.ts
git commit -m "feat(frontend): workflow hub types + api client functions"
```

---

### Task 3.2: Workflow Hub list page

**Files:**
- Create: `frontend/src/app/workspace/workflows/page.tsx`
- Create: `frontend/src/app/workspace/workflows/_components/workflow-hub-tree.tsx`
- Create: `frontend/src/app/workspace/workflows/_components/workflow-row.tsx`
- Create: `frontend/src/core/workflows/use-all-workflows.ts`
- Modify: `frontend/src/components/workspace/workspace-nav-chat-list.tsx` (add hub nav entry)

- [ ] **Step 1: Add the nav entry**

In `frontend/src/components/workspace/workspace-nav-chat-list.tsx`, after the existing two `SidebarMenuItem`s, add:

```tsx
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/workflows")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/workflows"
            >
              <ListChecksIcon />
              <span>{t.sidebar.workflows ?? "Workflows"}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
```

Update the `lucide-react` import at the top to include `ListChecksIcon`:

```tsx
import { BotIcon, ListChecksIcon, MessagesSquare } from "lucide-react";
```

(The `t.sidebar.workflows` key may not exist in i18n yet; the `?? "Workflows"` fallback keeps it from crashing. A real i18n entry can be added separately if/when the project's i18n flow demands it.)

- [ ] **Step 2: Create `use-all-workflows.ts`**

Create `frontend/src/core/workflows/use-all-workflows.ts`:

```ts
import { useQuery } from "@tanstack/react-query";

import { fetchAllWorkflows } from "./api";
import type { AllWorkflowsResponse } from "./types";

const HUB_REFRESH_MS = 3_000;

export function useAllWorkflows() {
  return useQuery<AllWorkflowsResponse>({
    queryKey: ["workflows", "all"],
    queryFn: ({ signal }) => fetchAllWorkflows(signal),
    refetchInterval: HUB_REFRESH_MS,
    refetchIntervalInBackground: false,
  });
}
```

- [ ] **Step 3: Create the row component**

Create `frontend/src/app/workspace/workflows/_components/workflow-row.tsx`:

```tsx
"use client";

import {
  CheckCircle2Icon,
  CircleDotIcon,
  CircleIcon,
  ExternalLinkIcon,
  TrashIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { WorkflowEntry } from "@/core/workflows/types";

const statusIcon: Record<WorkflowEntry["status"], React.ReactNode> = {
  running: <CircleDotIcon className="size-3.5 text-blue-500" />,
  done: <CheckCircle2Icon className="size-3.5 text-emerald-500" />,
  failed: <XCircleIcon className="size-3.5 text-red-500" />,
  cancelled: <CircleIcon className="size-3.5 text-muted-foreground" />,
};

interface Props {
  parentThreadId: string;
  workflow: WorkflowEntry;
  onCancel: (childThreadId: string) => void;
  onDelete: (childThreadId: string) => void;
}

function summarizeProgress(workflow: WorkflowEntry): string {
  if (workflow.status === "done" && workflow.report_preview) {
    return workflow.report_preview.slice(0, 80);
  }
  if (workflow.status === "failed" && workflow.error) {
    return workflow.error.slice(0, 80);
  }
  if (workflow.status === "cancelled") {
    return "Cancelled by user";
  }
  // running: render a few progress fields
  const entries = Object.entries(workflow.progress).slice(0, 3);
  if (entries.length === 0) return "starting…";
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(" · ");
}

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

export function WorkflowRow({
  parentThreadId,
  workflow,
  onCancel,
  onDelete,
}: Props) {
  const ts = workflow.finished_at ?? workflow.started_at;
  return (
    <li className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
      <Link
        href={`/workspace/workflows/${encodeURIComponent(workflow.child_thread_id)}`}
        className="flex flex-1 items-center gap-2 truncate"
      >
        {statusIcon[workflow.status]}
        <span className="font-medium">{workflow.name}</span>
        <span className="text-muted-foreground truncate">
          {summarizeProgress(workflow)}
        </span>
        <span className="text-muted-foreground ml-auto text-xs">
          {relativeTime(ts)}
        </span>
      </Link>
      <div className="hidden items-center gap-1 group-hover:flex">
        {workflow.status === "running" && (
          <Button
            size="icon"
            variant="ghost"
            className="size-7"
            title="Cancel"
            onClick={() => onCancel(workflow.child_thread_id)}
          >
            <XIcon className="size-3.5" />
          </Button>
        )}
        <Button asChild size="icon" variant="ghost" className="size-7">
          <Link
            href={`/workspace/chats/${encodeURIComponent(parentThreadId)}`}
            title="Go to parent chat"
          >
            <ExternalLinkIcon className="size-3.5" />
          </Link>
        </Button>
        {workflow.status !== "running" && (
          <Button
            size="icon"
            variant="ghost"
            className="size-7"
            title="Delete"
            onClick={() => onDelete(workflow.child_thread_id)}
          >
            <TrashIcon className="size-3.5" />
          </Button>
        )}
      </div>
    </li>
  );
}
```

- [ ] **Step 4: Create the tree component**

Create `frontend/src/app/workspace/workflows/_components/workflow-hub-tree.tsx`:

```tsx
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useAllWorkflows } from "@/core/workflows/use-all-workflows";
import {
  cancelActiveWorkflow,
} from "@/core/workflows/api";
import type { WorkflowParentGroup } from "@/core/workflows/types";
import { getBackendBaseURL } from "@/core/utils/get-backend-base-url";

import { WorkflowRow } from "./workflow-row";

function hasActive(p: WorkflowParentGroup): boolean {
  return p.workflows.some((w) => w.status === "running");
}

function ParentGroup({ parent }: { parent: WorkflowParentGroup }) {
  const [open, setOpen] = useState(hasActive(parent));
  const queryClient = useQueryClient();

  const cancelMut = useMutation({
    mutationFn: (childThreadId: string) =>
      cancelActiveWorkflow(parent.thread_id, childThreadId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["workflows", "all"] }),
    onError: (e: Error) => toast.error(`Cancel failed: ${e.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: async (childThreadId: string) => {
      const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
        childThreadId,
      )}`;
      const r = await fetch(url, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["workflows", "all"] }),
    onError: (e: Error) => toast.error(`Delete failed: ${e.message}`),
  });

  const title = parent.title?.trim() || `${parent.thread_id.slice(0, 8)}…`;
  const activeCount = parent.workflows.filter((w) => w.status === "running")
    .length;

  return (
    <div className="rounded-lg border">
      <Button
        variant="ghost"
        className="w-full justify-start gap-2 p-3 font-normal"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDownIcon className="size-4" />
        ) : (
          <ChevronRightIcon className="size-4" />
        )}
        <span className="font-medium">{title}</span>
        <span className="text-muted-foreground text-xs">
          ({parent.workflows.length} workflow
          {parent.workflows.length === 1 ? "" : "s"}
          {activeCount > 0 ? `, ${activeCount} active` : ""})
        </span>
      </Button>
      {open && (
        <ul className="border-t px-2 py-1">
          {parent.workflows.map((wf) => (
            <WorkflowRow
              key={wf.child_thread_id}
              parentThreadId={parent.thread_id}
              workflow={wf}
              onCancel={(c) => cancelMut.mutate(c)}
              onDelete={(c) => deleteMut.mutate(c)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

export function WorkflowHubTree() {
  const { data, isLoading, isError, error } = useAllWorkflows();

  if (isLoading) {
    return <div className="text-muted-foreground p-4 text-sm">Loading…</div>;
  }
  if (isError) {
    return (
      <div className="p-4 text-sm text-red-500">
        Failed to load workflows: {(error as Error).message}
      </div>
    );
  }
  const parents = data?.parents ?? [];
  if (parents.length === 0) {
    return (
      <div className="text-muted-foreground p-8 text-center text-sm">
        You haven&apos;t started any workflows yet. Try asking the assistant
        to start one in a chat (e.g. &quot;run demo-flow&quot;).
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {parents.map((p) => (
        <ParentGroup key={p.thread_id} parent={p} />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Create the page**

Create `frontend/src/app/workspace/workflows/page.tsx`:

```tsx
import { WorkflowHubTree } from "./_components/workflow-hub-tree";

export default function WorkflowsHubPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <h1 className="text-lg font-semibold">Workflows</h1>
        <p className="text-muted-foreground text-sm">
          All workflows you&apos;ve started, grouped by chat.
        </p>
      </div>
      <div className="flex-1 overflow-auto">
        <WorkflowHubTree />
      </div>
    </div>
  );
}
```

- [ ] **Step 6: typecheck + lint**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: PASS for files we created. (Pre-existing lint warnings in untouched files: leave alone.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/workspace/workflows/ \
        frontend/src/core/workflows/use-all-workflows.ts \
        frontend/src/components/workspace/workspace-nav-chat-list.tsx \
        frontend/src/core/workflows/api.ts frontend/src/core/workflows/types.ts
git commit -m "feat(frontend): /workspace/workflows hub list page with parent-grouped tree"
```

---

### Task 3.3: Workflow detail route + bidirectional chat panel

**Files:**
- Create: `frontend/src/app/workspace/workflows/[child_thread_id]/page.tsx`
- Create: `frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx`
- Create: `frontend/src/core/workflows/use-workflow-chat.ts`

The detail panel reads child thread state via the existing `/threads/{tid}/state` endpoint, posts new HumanMessages via the new endpoint, and computes ✓ / ✓✓ ack status.

- [ ] **Step 1: Find the existing thread-state fetch helper**

Run:
```bash
grep -rn "fetchThreadState\|/threads.*/state" frontend/src/core/ --include="*.ts" --include="*.tsx" | head
```

Find the function that fetches `/api/threads/{tid}/state`. If it doesn't exist as a reusable function, create one in `frontend/src/core/threads/api.ts` (look for that file first).

If absent, add to `frontend/src/core/threads/api.ts`:

```ts
export interface ThreadStateSnapshot {
  values: Record<string, unknown>;
  next: string[];
  metadata: Record<string, unknown>;
  checkpoint: { id: string | null; ts: string };
  checkpoint_id: string | null;
  parent_checkpoint_id: string | null;
  created_at: string;
  tasks: Array<{ id: string; name: string }>;
}

export async function fetchThreadState(
  threadId: string,
  signal?: AbortSignal,
): Promise<ThreadStateSnapshot> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    threadId,
  )}/state`;
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(`fetchThreadState: HTTP ${r.status}`);
  return (await r.json()) as ThreadStateSnapshot;
}
```

- [ ] **Step 2: Create `use-workflow-chat.ts`**

Create `frontend/src/core/workflows/use-workflow-chat.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchThreadState,
  type ThreadStateSnapshot,
} from "../threads/api";

import { postWorkflowMessage } from "./api";

const POLL_MS = 1500;

export interface WorkflowMessage {
  id: string;
  role: "human" | "ai";
  content: string;
  ts?: string;
}

export interface AckStatus {
  /** ✓: server confirmed write. ✓✓: workflow consumed (later AIMessage or
   *  progress field changed since the user message). */
  acked: boolean;
  consumed: boolean;
}

function extractMessages(state: ThreadStateSnapshot | undefined): WorkflowMessage[] {
  const raw = state?.values?.messages;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((m: unknown) => {
      if (!m || typeof m !== "object") return null;
      const obj = m as Record<string, unknown>;
      const type = obj.type;
      const id = String(obj.id ?? "");
      const content = typeof obj.content === "string" ? obj.content : "";
      if (type === "human") {
        return { id, role: "human", content } as WorkflowMessage;
      }
      if (type === "ai") {
        return { id, role: "ai", content } as WorkflowMessage;
      }
      return null;
    })
    .filter(Boolean) as WorkflowMessage[];
}

export function useWorkflowChat(
  parentThreadId: string,
  childThreadId: string,
) {
  const queryClient = useQueryClient();
  const stateQuery = useQuery<ThreadStateSnapshot>({
    queryKey: ["workflow-chat", childThreadId],
    queryFn: ({ signal }) => fetchThreadState(childThreadId, signal),
    refetchInterval: POLL_MS,
  });

  const messages = extractMessages(stateQuery.data);

  const sendMut = useMutation({
    mutationFn: (content: string) =>
      postWorkflowMessage(parentThreadId, childThreadId, { content }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["workflow-chat", childThreadId],
      }),
  });

  return {
    messages,
    progress: (stateQuery.data?.values ?? {}) as Record<string, unknown>,
    isLoading: stateQuery.isLoading,
    error: stateQuery.error as Error | null,
    send: sendMut.mutate,
    isSending: sendMut.isPending,
    sendError: sendMut.error as Error | null,
  };
}
```

- [ ] **Step 3: Create `workflow-chat-panel.tsx`**

Create `frontend/src/app/workspace/workflows/[child_thread_id]/_components/workflow-chat-panel.tsx`:

```tsx
"use client";

import { CheckIcon, CheckCheckIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cancelActiveWorkflow } from "@/core/workflows/api";
import {
  useWorkflowChat,
  type WorkflowMessage,
} from "@/core/workflows/use-workflow-chat";
import type { WorkflowEntry } from "@/core/workflows/types";

interface Props {
  parentThreadId: string;
  workflow: WorkflowEntry;
}

function isTerminal(status: WorkflowEntry["status"]): boolean {
  return status === "done" || status === "failed" || status === "cancelled";
}

/** ✓ if server has the message; ✓✓ if any AIMessage or progress change
 *  followed it. We approximate "followed" by: index in messages array;
 *  any later message OR any progress field present beyond minimum. */
function ackFor(
  msg: WorkflowMessage,
  index: number,
  all: WorkflowMessage[],
): "sent" | "consumed" {
  if (index < all.length - 1) return "consumed";
  return "sent";
}

export function WorkflowChatPanel({ parentThreadId, workflow }: Props) {
  const { messages, progress, isLoading, send, isSending } = useWorkflowChat(
    parentThreadId,
    workflow.child_thread_id,
  );
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // Autoscroll to bottom on new messages
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  const terminal = isTerminal(workflow.status);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b p-3">
        <span className="font-medium">{workflow.name}</span>
        <span className="text-muted-foreground text-sm">
          · {workflow.status}
          {workflow.progress &&
            Object.keys(workflow.progress).length > 0 &&
            " · " +
              Object.entries(workflow.progress)
                .slice(0, 3)
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(" · ")}
        </span>
        {!terminal && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={async () => {
              try {
                await cancelActiveWorkflow(
                  parentThreadId,
                  workflow.child_thread_id,
                );
              } catch (e) {
                toast.error(`Cancel failed: ${(e as Error).message}`);
              }
            }}
          >
            <XIcon className="size-3.5" /> Cancel
          </Button>
        )}
      </div>

      {/* Terminal summary card */}
      {terminal && (
        <div className="bg-muted/50 m-3 rounded-lg border p-3 text-sm">
          {workflow.status === "done" && workflow.report_preview && (
            <pre className="whitespace-pre-wrap font-sans">
              {workflow.report_preview}
            </pre>
          )}
          {workflow.status === "failed" && (
            <span className="text-red-600">{workflow.error ?? "Failed"}</span>
          )}
          {workflow.status === "cancelled" && (
            <span className="text-muted-foreground">
              Cancelled by user{workflow.error ? `: ${workflow.error}` : ""}
            </span>
          )}
        </div>
      )}

      {/* Messages */}
      <div ref={listRef} className="flex-1 space-y-2 overflow-auto p-3">
        {isLoading && (
          <div className="text-muted-foreground text-sm">Loading…</div>
        )}
        {messages.length === 0 && !isLoading && (
          <div className="text-muted-foreground text-center text-sm">
            No messages yet.
          </div>
        )}
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
      </div>

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            placeholder={
              terminal ? "Workflow has ended" : "Send a message to the workflow…"
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={terminal || isSending}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (draft.trim()) {
                  send(draft.trim());
                  setDraft("");
                }
              }
            }}
            className="min-h-[60px]"
          />
          <Button
            disabled={terminal || isSending || !draft.trim()}
            onClick={() => {
              if (draft.trim()) {
                send(draft.trim());
                setDraft("");
              }
            }}
          >
            Send
          </Button>
        </div>
        <div className="text-muted-foreground mt-1 text-xs">
          Enter to send · Shift+Enter for newline
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create the detail page**

Create `frontend/src/app/workspace/workflows/[child_thread_id]/page.tsx`:

```tsx
"use client";

import { ChevronLeftIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAllWorkflows } from "@/core/workflows/use-all-workflows";

import { WorkflowChatPanel } from "./_components/workflow-chat-panel";

export default function WorkflowDetailPage() {
  const params = useParams<{ child_thread_id: string }>();
  const childTid = params?.child_thread_id ?? "";
  const { data, isLoading } = useAllWorkflows();

  // Locate the workflow + its parent across the hub tree
  let parentThreadId: string | null = null;
  let workflow = null;
  for (const p of data?.parents ?? []) {
    const found = p.workflows.find((w) => w.child_thread_id === childTid);
    if (found) {
      parentThreadId = p.thread_id;
      workflow = found;
      break;
    }
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground p-4 text-sm">Loading…</div>
    );
  }

  if (!workflow || !parentThreadId) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b p-3">
          <Button asChild variant="ghost" size="sm">
            <Link href="/workspace/workflows">
              <ChevronLeftIcon className="size-4" /> Back to workflows
            </Link>
          </Button>
        </div>
        <div className="text-muted-foreground p-8 text-center text-sm">
          Workflow not found.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <Button asChild variant="ghost" size="sm">
          <Link href="/workspace/workflows">
            <ChevronLeftIcon className="size-4" /> Back to workflows
          </Link>
        </Button>
      </div>
      <div className="flex-1 overflow-hidden">
        <WorkflowChatPanel
          parentThreadId={parentThreadId}
          workflow={workflow}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: typecheck + lint**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: PASS for new files. Fix any issues in our files.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/workspace/workflows/[child_thread_id]/ \
        frontend/src/core/workflows/use-workflow-chat.ts \
        frontend/src/core/threads/api.ts
git commit -m "feat(frontend): workflow detail route with bidirectional chat panel"
```

---

### Task 3.4: Stage 3 verification

- [ ] **Step 1: Frontend full check**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: pass for all files we touched.

- [ ] **Step 2: Manual smoke test**

```bash
# Terminal A
cd backend && uv run uvicorn app.gateway.main:app --port 8001
# Terminal B
cd frontend && pnpm dev
```

Open http://localhost:3000/workspace/workflows. Confirm:
- Page renders without runtime error.
- Empty state shows when no workflows started.
- Start a demo-flow from chat: it appears in hub.
- Click into detail: chat panel renders, can send messages.

(If backend isn't producing demo-flow data because tests broke a dependency, that's a stage 1 regression — go back and fix.)

---

## Stage 4: Lead Agent Workflow Startup Guidance

### Task 4.1: Backend — extend `start_workflow` tool message with structured link

**Files:**
- Modify: `backend/packages/harness/deerflow/workflows/tools.py`
- Test: `backend/tests/test_workflows_tools.py` (existing)

The `_tool_msg` helper currently returns a plain `ToolMessage`. We extend it (or add a sibling helper) so `start_workflow` can attach `additional_kwargs` carrying the structured link payload.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflows_tools.py`:

```python
@pytest.mark.asyncio
async def test_start_workflow_tool_message_carries_workflow_link_payload(monkeypatch):
    """The ToolMessage returned by start_workflow must carry an
    additional_kwargs.workflow_link payload so the frontend can render
    a clickable card."""
    import deerflow.workflows.tools as wftools
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from pydantic import BaseModel

    class _Input(BaseModel):
        x: int = 1

    spec = WorkflowSpec(
        name="demo-flow", description="x", factory=lambda **k: object(),
        input_schema=_Input, done_field="is_done",
        report_field="report_markdown", progress_fields=[],
    )
    monkeypatch.setattr(
        wftools, "_REGISTRY", WorkflowRegistry([spec], []), raising=False,
    )
    # Stub run_workflow_background so no real task starts
    async def fake_run(**kwargs):
        return None
    monkeypatch.setattr(wftools, "run_workflow_background", fake_run)

    # Stub _record_child_workflow_thread to a no-op
    async def fake_record(*a, **k): return None
    monkeypatch.setattr(wftools, "_record_child_workflow_thread", fake_record)

    monkeypatch.setattr(
        "deerflow.runtime.checkpointer_singleton.get_default_checkpointer",
        lambda: object(),
    )

    from deerflow.workflows.tools import start_workflow

    cmd = await start_workflow.ainvoke({
        "name": "demo-flow",
        "params": {"x": 5},
        "tool_call_id": "tc1",
        "config": {"configurable": {"thread_id": "parent-1"}},
    })

    msg = cmd.update["messages"][0]
    payload = msg.additional_kwargs
    assert payload.get("element") == "workflow_link", (
        f"expected element='workflow_link' for frontend dispatch, got "
        f"additional_kwargs={payload!r}"
    )
    link = payload.get("workflow_link")
    assert isinstance(link, dict)
    assert link["name"] == "demo-flow"
    assert link["child_thread_id"]
    assert link["url"] == f"/workspace/workflows/{link['child_thread_id']}"

    # Text content must still mention the hub for non-rich-UI clients
    assert "工作流中心" in msg.content or "Workflow Hub" in msg.content
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && uv run pytest tests/test_workflows_tools.py::test_start_workflow_tool_message_carries_workflow_link_payload -v`
Expected: FAIL — current `_tool_msg` doesn't attach `additional_kwargs`.

- [ ] **Step 3: Extend `_tool_msg` and update `start_workflow` return**

In `backend/packages/harness/deerflow/workflows/tools.py`, extend `_tool_msg`:

```python
def _tool_msg(
    content: str,
    tool_call_id: str,
    *,
    additional_kwargs: dict[str, Any] | None = None,
) -> Command:
    msg = ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        additional_kwargs=additional_kwargs or {},
    )
    return Command(update={"messages": [msg]})
```

Then change the success-path return in `start_workflow` (currently lines 124-128) to:

```python
    text = (
        f"已为你启动工作流 {name!r}(thread_id={child_tid})。\n"
        f"你可以在「工作流中心」(/workspace/workflows)查看进度并直接给它发送提示。\n"
        f"也可以使用 get_workflow_progress / inject_hint / cancel_workflow 工具。"
    )
    return _tool_msg(
        text,
        tool_call_id,
        additional_kwargs={
            "element": "workflow_link",
            "workflow_link": {
                "child_thread_id": child_tid,
                "name": name,
                "url": f"/workspace/workflows/{child_tid}",
            },
        },
    )
```

- [ ] **Step 4: Run test to verify pass + full tools tests**

Run: `cd backend && uv run pytest tests/test_workflows_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/workflows/tools.py backend/tests/test_workflows_tools.py
git commit -m "feat(workflows): start_workflow tool message carries workflow_link payload"
```

---

### Task 4.2: Frontend — render `workflow_link` tool message as clickable card

**Files:**
- Modify: `frontend/src/components/workspace/messages/message-list-item.tsx`

The existing renderer already special-cases `additional_kwargs?.element === "task"` (line ~187 — see `subtask-card.tsx`). We follow the same pattern for `workflow_link`.

- [ ] **Step 1: Locate the dispatch site**

Run:
```bash
grep -n "additional_kwargs?.element" frontend/src/components/workspace/messages/message-list-item.tsx
```

Note the line(s); you'll branch right after the existing `"task"` case.

- [ ] **Step 2: Create the workflow-link card component**

Create `frontend/src/components/workspace/messages/workflow-link-card.tsx`:

```tsx
"use client";

import { ListChecksIcon, ArrowRightIcon } from "lucide-react";
import Link from "next/link";

interface Props {
  childThreadId: string;
  name: string;
  url: string;
}

export function WorkflowLinkCard({ childThreadId, name, url }: Props) {
  return (
    <Link
      href={url}
      className="bg-muted/50 hover:bg-muted flex items-center gap-3 rounded-lg border p-3 transition-colors"
    >
      <ListChecksIcon className="size-5 text-blue-500" />
      <div className="flex-1">
        <div className="text-sm font-medium">View workflow: {name}</div>
        <div className="text-muted-foreground text-xs font-mono">
          {childThreadId.slice(0, 8)}…
        </div>
      </div>
      <ArrowRightIcon className="size-4 opacity-60" />
    </Link>
  );
}
```

- [ ] **Step 3: Wire it into the renderer**

In `frontend/src/components/workspace/messages/message-list-item.tsx`, locate the existing branch (around line 187):

```tsx
  if (message.additional_kwargs?.element === "task") {
```

Add a parallel branch right after the closing brace of that block:

```tsx
  if (message.additional_kwargs?.element === "workflow_link") {
    const link = message.additional_kwargs.workflow_link as
      | {
          child_thread_id: string;
          name: string;
          url: string;
        }
      | undefined;
    if (link) {
      return (
        <div className="my-2 space-y-2">
          {message.content && typeof message.content === "string" && (
            <div className="text-muted-foreground whitespace-pre-wrap text-sm">
              {message.content}
            </div>
          )}
          <WorkflowLinkCard
            childThreadId={link.child_thread_id}
            name={link.name}
            url={link.url}
          />
        </div>
      );
    }
  }
```

Add the import at the top of the file:

```tsx
import { WorkflowLinkCard } from "./workflow-link-card";
```

- [ ] **Step 4: typecheck + lint**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/messages/workflow-link-card.tsx \
        frontend/src/components/workspace/messages/message-list-item.tsx
git commit -m "feat(frontend): render workflow_link tool message as clickable card"
```

---

### Task 4.3: Stage 4 verification

- [ ] **Step 1: Backend tests**

Run: `cd backend && uv run pytest 2>&1 | tail -10`
Expected: all pass.

- [ ] **Step 2: Frontend checks**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: pass.

- [ ] **Step 3: Manual smoke**

Start a workflow from a chat. Verify:
- The lead agent's reply contains the structured card pointing at `/workspace/workflows/<child_tid>`.
- Clicking the card navigates to the detail page.

---

## Stage 5: Old UX Removal

### Task 5.1: Delete `ActiveWorkflowsPanel` and friends

**Files:**
- Delete: `frontend/src/components/workspace/active-workflows-panel/` (whole dir)
- Modify: `frontend/src/components/workspace/workspace-sidebar.tsx`
- Delete: `frontend/src/core/threads/use-thread-viewed.ts`
- Modify: `frontend/src/components/workspace/recent-chat-list.tsx` (remove `hasUnreadFinish` usage)
- Modify: `frontend/src/core/workflows/hooks.ts` (remove `useActiveWorkflows`-driven invalidation; can keep the cancel mutation hook as it's used by hub)

Note: `useCurrentChatThreadId` is no longer used by `ActiveWorkflowsPanel`, but keep the file (other features may depend on it; do not delete unless grep confirms zero usage).

- [ ] **Step 1: Audit usages before deleting**

```bash
cd frontend
grep -rn "ActiveWorkflowsPanel\|active-workflows-panel" src/ --include="*.ts" --include="*.tsx"
grep -rn "useThreadViewed\|hasUnreadFinish" src/ --include="*.ts" --include="*.tsx"
grep -rn "useActiveWorkflows" src/ --include="*.ts" --include="*.tsx"
grep -rn "useCurrentChatThreadId" src/ --include="*.ts" --include="*.tsx"
```

Inventory which files need updating before any deletes.

- [ ] **Step 2: Update `workspace-sidebar.tsx`**

Remove the import line and the `<ActiveWorkflowsPanel />` usage. The file should look like:

```tsx
"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

import { RecentChatList } from "./recent-chat-list";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { open: isSidebarOpen } = useSidebar();
  return (
    <>
      <Sidebar variant="sidebar" collapsible="icon" {...props}>
        <SidebarHeader className="py-0">
          <WorkspaceHeader />
        </SidebarHeader>
        <SidebarContent>
          <WorkspaceNavChatList />
          {isSidebarOpen && <RecentChatList />}
        </SidebarContent>
        <SidebarFooter>
          <WorkspaceNavMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </>
  );
}
```

- [ ] **Step 3: Update `recent-chat-list.tsx`**

In `frontend/src/components/workspace/recent-chat-list.tsx`:
- Remove the import line containing `hasUnreadFinish, useThreadViewed`.
- Remove the `const { lastViewedAt, markViewed } = useThreadViewed();` line.
- Remove the JSX block that renders the red dot via `hasUnreadFinish(...)` (around line 201).
- If `markViewed` was called anywhere, remove those calls.

The exact edits depend on what's there; view the file first:

```bash
view frontend/src/components/workspace/recent-chat-list.tsx
```

Apply the deletions to leave a clean component that just lists chats without any workflow-finish indicators.

- [ ] **Step 4: Trim `core/workflows/hooks.ts`**

The `useActiveWorkflows` hook is no longer used anywhere (the hub uses `useAllWorkflows`). Check:

```bash
grep -rn "useActiveWorkflows" frontend/src/
```

If the only remaining users are in deleted files, remove `useActiveWorkflows` and its export. Keep `useCancelActiveWorkflow` (used by both old code paths and the new hub).

If after editing `hooks.ts` there are unused imports (e.g. `bumpThreadReloadTick`), remove them — but only if tsc/eslint complain. Do not remove them speculatively.

- [ ] **Step 5: Delete the old panel directory and the thread-viewed module**

```bash
cd frontend
git rm -r src/components/workspace/active-workflows-panel
git rm src/core/threads/use-thread-viewed.ts
```

If grep in step 1 showed `use-current-chat-thread-id.ts` has zero remaining usages, delete it too (otherwise leave it).

- [ ] **Step 6: typecheck + lint**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: PASS. Most likely failures here are stale imports — fix them by removing the imports.

- [ ] **Step 7: Manual smoke**

Run dev:
```bash
cd frontend && pnpm dev
```

Visit `/workspace/chats/<some_thread_id>`. Confirm:
- No `ActiveWorkflowsPanel` visible in sidebar.
- No red dots in chat list.
- Sidebar still shows Chats / Agents / Workflows nav entries.
- Workflow Hub still works.

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src/
git commit -m "feat(frontend): remove ActiveWorkflowsPanel, hasUnreadFinish, useThreadViewed"
```

---

### Task 5.2: Final sweep

- [ ] **Step 1: Run full backend suite**

Run: `cd backend && uv run pytest 2>&1 | tail -5`
Expected: all pass.

- [ ] **Step 2: Run full frontend checks**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: pass.

- [ ] **Step 3: Final manual smoke**

End-to-end flow:
1. `make dev` from repo root.
2. Open `http://localhost:2026`.
3. Start a chat, ask the assistant to "run the demo-flow workflow".
4. Verify: assistant reply shows a clickable workflow card.
5. Click the card → land on workflow detail page.
6. Send a message ("hello workflow") → see ✓ then ✓✓ as the workflow processes it.
7. Visit `/workspace/workflows` → see the workflow under its parent chat.
8. Cancel a running workflow from the hub → it transitions to "cancelled" status.
9. Delete a finished workflow from the hub → it disappears.
10. Visit chat list → no red dots, no `ActiveWorkflowsPanel`.

- [ ] **Step 4: Commit any final cleanups**

```bash
git status
# If anything dangling, commit; else skip
```

- [ ] **Step 5: Update STATUS doc (if project follows that pattern)**

Optionally append a section to `docs/superpowers/STATUS-2026-04-28.md` summarizing the redesign as a single ship. Skip if not required.
