# Workflow UI Redesign — Detail, History, Global Hub

Date: 2026-04-29
Status: design (ready for plan)

## Goal

Replace the current "active workflows panel" UX (a chat-page sidebar showing
only running children) with a platform-level workflow experience:

1. **Workflow Hub** — a top-level navigation entry alongside `/workspace/chats`.
2. **Workflow Detail** — a true bidirectional chat view per workflow,
   covering both live and historical workflows.
3. **In-UI message injection** — users (and the lead agent) inject hints by
   sending real `HumanMessage`s into the workflow's own thread.

The redesign serves both end-users (who want to know "what is this workflow
doing / what did it produce") and developers (who occasionally need raw
state / trace), with a single primary surface plus an optional technical
detail expander.

## Non-Goals

- Workflow scheduling, queueing, dependency DAGs.
- Workflow templates / presets / parameter UIs.
- Workflow analytics dashboards.
- "Restart this workflow" affordance (deliberately omitted; can be added later).
- Workflow-to-workflow injection.

## Background — Current State (2026-04-29)

- Each `start_workflow` tool call spawns a **child thread** registered in
  `_THREAD_TO_WORKFLOW` and `_BG_TASKS` (`workflows/tools.py`).
- The child runs a Pregel graph (e.g. `demo_flow`) on the shared
  checkpointer, writes `progress_fields` and a `done_field` to its state,
  and on completion emits an `AIMessage` into the **parent** thread via
  `emit_to_parent_thread` (`workflows/emit.py`).
- Hints from the parent are sent through `inject_hint` (LLM tool) →
  `hints_inbox.py` (in-process dict) → `pop_hints()` at the start of each
  workflow node tick. Hints are **not** part of the child's checkpoint state.
- The frontend exposes:
  - `ActiveWorkflowsPanel` (sidebar in chat page) listing live children with
    a progress bar, a cancel button, and a "completed → red dot" mechanism
    on the parent thread in the chat list.
  - Polls `/threads/{p}/workflows/active` every 2s; bumps a per-thread
    reload tick when active count drops, so the chat page refetches state
    and renders the workflow's emitted AIMessage.
- The lead agent has tools `start_workflow`, `inject_hint`,
  `get_workflow_progress`, `cancel_workflow`.

Pain points the redesign addresses:

- No history view: completed workflows disappear from the panel; users have
  no way to revisit "what was that workflow's final report?".
- No cross-thread aggregation: a user who started workflows from five
  different chats has no central place to see them.
- Injection requires asking the lead agent to call `inject_hint`, which goes
  through LLM reasoning and is opaque ("did the agent actually inject?").
- Hints are write-only and one-tick-lived; users can't see "what hints did I
  send to this workflow?".

## Design

### A. Domain model changes

**WorkflowSpec** — add `accepts_chat: bool` (default `False`).
Specs that opt in must define a `messages` channel in their state schema
(see B). Frontend hides the input box when `accepts_chat=False`.

**State schema (per opted-in workflow)** — must include:

```python
class DemoFlowState(TypedDict):
    # existing business fields ...
    epoch: int
    best_score: float
    done: bool
    report: str | None

    # new chat-channel fields
    messages: Annotated[list[AnyMessage], add_messages]
    _seen_msg_ids: set[str]
```

`_seen_msg_ids` is a workflow-author concern: it tracks which inbound
`HumanMessage`s have already been incorporated into a node's prompt, so the
same hint isn't re-fed to the inner LLM on every tick. The framework
neither writes nor reads it.

### B. Message channel as the single bidirectional pipe

All workflow ↔ user / agent communication goes through the workflow's own
`messages` channel:

- **User → workflow** (UI direct injection or `inject_hint` tool): append a
  `HumanMessage` to the child thread's `messages` channel via
  `aupdate_state` (same mechanism as `emit_to_parent_thread`, just inverted
  target + role).
- **Workflow → user**: nodes return `{"messages": [AIMessage(...)]}` in
  their normal output; LangGraph's `add_messages` reducer appends.

Workflow nodes are responsible for:

1. Filtering `state["messages"]` for new `HumanMessage`s
   (`m.id not in state["_seen_msg_ids"]`).
2. Passing those messages **as-is** into the node's existing LLM call
   (research agent, tool-calling agent, etc.) — the LLM does the semantic
   interpretation. No keyword matching, no if/else on message content.
3. Updating `_seen_msg_ids` in the return dict.
4. Optionally appending an `AIMessage` reply when the LLM has something
   user-facing to say (the LLM decides; if it just acknowledges, fine; if
   it answers a status query, fine; if it stays silent and only progresses
   business state, also fine — visual ack handles user feedback).

### C. Visual receipts (no template ack)

The framework does **not** auto-write "message received" ack `AIMessage`s.
Instead, the frontend renders user-bubble receipts:

- **(no mark)** — POST not yet returned.
- **✓** — POST `200`; the `HumanMessage` is in the child's checkpoint.
- **✓✓** — On a subsequent state poll, either:
  - `messages` length grew with a new `AIMessage` whose timestamp/checkpoint
    is after the user message, **or**
  - any `progress_field` value changed after the user message.

✓✓ thus means "the workflow has acted on this message" without requiring
the workflow to write a confirmation message.

### D. Hint execution path (P1 ride-along)

`work_loop_node` (and equivalents) feed new `HumanMessage`s into the
inner research-agent LLM as part of the prompt. The LLM:

- For instructions ("multiply dropout") → adjusts plan/config in its
  reasoning, optionally narrates "ok, dropout=0.3 this round".
- For status queries ("what epoch?") → answers from current state.
- For chitchat ("hmm") → may stay silent or briefly acknowledge.

Workflows whose nodes have **no** LLM call (pure scripts) should set
`accepts_chat=False`; the input box is hidden and they receive no hints.

### E. Frontend — Workflow Hub

**Route**: `/workspace/workflows` (new top-level entry in workspace
sidebar, beside `chats`).

**Layout**: single column, no double-pane. Tree of parent threads.

```
工作流中心
├─ 关于 demo-flow 训练实验的探讨        (3 个工作流, 1 活跃)   [创建于 2 天前]
│   ● demo-flow #3   running   epoch 3/5 · score=0.78    2 分钟前   ⋯
│   ✓ demo-flow #2   done      最终 score=0.82           昨天      ⋯
│   ✗ demo-flow #1   failed    OutOfMemoryError          3 天前    ⋯
├─ 关于客户分析报告                     (2 个工作流)
└─ ...
```

- **Parent ordering**: by parent thread `created_at` desc.
- **Default expansion**: parents that contain at least one active workflow
  are expanded; pure-history parents are collapsed.
- **Visibility**: parents with zero workflows are not shown.
- **Parent label**: parent thread's `title`; fallback to `thread_id[:8]`.
- **Child rows**: status dot + workflow name + short summary
  (`progress_fields` snippet for live; `report` first line for done;
  error class for failed; "cancelled by user" for cancelled) + relative
  time. Hover reveals quick-action icons:
  - **打开** → navigate to detail route.
  - **取消** (only when running).
  - **跳到父会话** → opens the parent chat thread.
  - **删除** → deletes child thread (cleans state + checkpoint, removes
    from parent's `metadata.child_workflow_threads`).

### F. Frontend — Workflow Detail

**Route**: `/workspace/workflows/<child_thread_id>` (separate route,
full-screen, breadcrumb back to hub).

**Active workflow** layout:

```
┌─ demo-flow · running · epoch 3/5 · score 0.78  ────── [×] 取消 ┐
│                                                                │
│  ┌────────────────────────────┐                                │
│  │ 收到 dropout 建议,本轮调到 │  workflow                     │
│  │ 0.3 试试                    │                                │
│  └────────────────────────────┘                                │
│                                                                │
│                            ┌──────────────────────────┐        │
│                            │ 多用 dropout              │ ✓✓   │
│                            └──────────────────────────┘        │
│                                                                │
│  ┌────────────────────────────┐                                │
│  │ epoch 3 done, score=0.78    │  workflow                     │
│  └────────────────────────────┘                                │
│                                                                │
│                            ┌──────────────────────────┐        │
│                            │ 现在第几轮?               │ ✓    │
│                            └──────────────────────────┘        │
│                                                                │
│  ▍流式生成中: "目前在第 4 轮 ..."                              │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│ [ 给工作流发消息...                              ]   [发送]   │
└────────────────────────────────────────────────────────────────┘
```

**Terminal workflow** layout — same component, with adaptations:

- Top status banner replaced by a **sticky terminal summary card**:
  - `done`: report content (markdown rendered).
  - `failed`: error class + first stack frame.
  - `cancelled`: "Cancelled at HH:MM:SS by user" + the cancellation
    `AIMessage` if present.
- Cancel button hidden.
- Input box disabled with placeholder "工作流已结束".
- All historical messages and the final `progress_fields` are still shown.

A small "技术细节" expander at the top opens a panel with the raw state
JSON (channel values) and a link to LangGraph Studio if available
(`http://localhost:2024/?thread=<child_id>`). Stretch — not required for
v1.

### G. Frontend — what's removed from chat page

- `frontend/src/components/workspace/active-workflows-panel/` — entire
  directory deleted. The chat page no longer shows a workflow widget.
- `useThreadViewed` store + `hasUnreadFinish` red-dot logic in chat list —
  removed. Users discover workflows via the lead agent's reply (see H) and
  the workspace sidebar's Workflow Hub entry.
- `frontend/src/core/threads/use-current-chat-thread-id.ts` — kept (still
  used by other features, e.g. potential future per-thread filtering).

### H. Lead agent — workflow startup guidance

When `start_workflow` succeeds, the tool message must guide the user to the
hub. Two layers:

1. **Text guidance** (always present, baseline):
   ```
   已为你启动 demo-flow 工作流(thread_id=<id>)。
   你可以在「工作流中心」查看进度并直接给它发送提示。
   ```
   The LLM naturally relays this in its conversational reply, so it works
   even when the message is forwarded to Slack/Feishu.

2. **Structured link** (web UI enhancement):
   The tool message also carries an `additional_kwargs` field
   (or response metadata, depending on what the lead agent's chat UI
   already inspects):
   ```python
   _tool_msg(
       text,
       tool_call_id,
       extra={"workflow_link": {
           "child_thread_id": child_id,
           "name": spec.name,
           "url": f"/workspace/workflows/{child_id}",
       }},
   )
   ```
   The frontend's tool-message renderer (when it sees a `workflow_link`
   payload) renders a clickable card "→ 查看工作流 demo-flow"
   alongside the text. Without the renderer, users still see the text
   guidance.

### I. Backend API additions

```
POST /api/threads/{parent_id}/workflows/{child_id}/messages
     body: {"content": str}
     -> {"ok": True}                       — append HumanMessage to child
     -> 404 if child_id not registered

GET  /api/workflows/all
     -> {
       "parents": [
         {
           "thread_id": "<parent_tid>",
           "title": "...",
           "created_at": "...",
           "workflows": [
             {
               "child_thread_id": "...",
               "name": "demo-flow",
               "status": "running"|"done"|"failed"|"cancelled",
               "started_at": "...",
               "finished_at": "..." | null,
               "progress": {...},          # progress_fields snapshot
               "report_preview": "..." | null,
               "error": "..." | null,
             },
             ...
           ],
         },
         ...
       ]
     }
```

`GET /api/workflows/all` is the single endpoint backing the hub list. It
walks all parent threads in the Store, filters those with non-empty
`metadata.child_workflow_threads`, loads each child's checkpoint to
classify status, and returns a denormalized tree.

`DELETE /api/threads/{tid}` already cascades into child workflow threads
(commit `827acd91`); the hub's "delete" quick action calls
`DELETE /api/threads/{child_tid}` directly.

The existing endpoints stay:

- `GET  /api/threads/{tid}/workflows/active` — still used internally by
  the hub if/when a "live count" indicator is needed elsewhere.
- `POST /api/threads/{tid}/workflows/{cid}/cancel` — unchanged.

### J. Backend — what's removed

- `backend/packages/harness/deerflow/workflows/hints_inbox.py` — entire
  module. `pop_hints` / `peek_hints` / `push_hint` / `reset_inbox` all
  gone.
- All `pop_hints` call sites in workflow nodes
  (`workflows/demo_flow/nodes/work_loop_node.py`, etc.) — replaced by
  `state["messages"]` consumption.
- `inject_hint` tool: signature and LLM-facing description **kept**.
  Implementation rewritten to call the same internal helper as
  `POST /threads/.../messages` — i.e. write a `HumanMessage` to the child
  thread's `messages` channel via `aupdate_state`.
- `_hints` field in any workflow state schema — removed (replaced by
  `messages`).

### K. Backend — what's kept

- `get_workflow_progress` tool — kept. LLM still has an explicit
  progress-query path that doesn't require it to read & summarise the
  child's `messages` channel itself.
- `_filter_workflow_child_threads` in `/threads/search` — kept (children
  must not appear in the user's chat list).
- `emit_to_parent_thread` — kept (terminal events still emit a summary
  `AIMessage` to the parent thread; this is independent of the in-workflow
  chat channel).
- `stamp_parent_finish` + parent-idle wait — kept.
- Cancel endpoint's wait-for-cleanup behaviour (commit `3e3f04d6`) — kept.

## Migration

1. Land schema + tool changes in one commit (state field added,
   `inject_hint` rewritten, `hints_inbox` deleted, demo_flow nodes updated).
2. Land backend endpoint additions (`POST .../messages`,
   `GET /workflows/all`).
3. Land frontend hub route + detail route.
4. Land lead-agent tool message structured link + frontend renderer.
5. Land removal of `ActiveWorkflowsPanel`, red-dot mechanism, related
   stores.

Each step ships passing tests. The redesign has no live-data migration
concerns: ongoing workflows from before this lands will simply be missing
the `messages` field; the hub treats their detail page as
"history-only with no chat" by virtue of no messages being present, and
the input box can either be disabled (because `accepts_chat=True`
requires migration) or — simpler — we let the spec's `accepts_chat`
default to `False` so legacy specs are auto-excluded from the chat UX
until their authors opt in.

## Open Questions

- **Pre-existing in-flight workflow when this lands**: If a user has a
  workflow running at the moment of deploy, its state schema won't include
  `messages`. The new chat panel handles this gracefully (no input,
  history-only display). The cancel button still works. No data migration
  needed; just don't break.
- **`inject_hint` semantics change**: The tool now writes through to a
  durable `messages` channel (not an in-memory dict). Existing tests that
  monkey-patch `hints_inbox` will need to update to assert on `aupdate_state`
  calls. Acceptable churn.
- **Hub list pagination**: For users with hundreds of parent threads,
  `GET /workflows/all` may grow large. v1 returns all; if performance
  becomes a problem, add cursor-based pagination later. Not blocking.

## Risks

- **Workflow nodes that don't currently consume `messages`** but live in
  the same codebase will break compilation (state schema mismatch). Audit
  all workflow specs in `workflows/` and either opt them in or leave them
  on the legacy schema (without `messages`). The framework should not
  force-add the field.
- **`add_messages` reducer unifies HumanMessage/AIMessage** without a
  separate event type for "user injection vs. tool output". If we later
  want richer event types (e.g. uploaded file, structured directive),
  we'll need a discriminator. v1 is fine with plain text content.
- **`_seen_msg_ids` is a per-workflow author concern**: easy to forget,
  causing the same hint to be re-fed to the LLM each tick. Document in
  the WorkflowSpec author guide; consider providing a helper
  `consume_new_user_messages(state)` that returns new messages and
  updates the seen-set.
