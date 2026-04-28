# Child Workflow Widget — Design (Phase 2)

Date: 2026-04-28
Status: design approved, awaiting plan

Phase 1 ([spec](./2026-04-28-custom-workflow-agent-platform-design.md))
delivered the backend platform: `start_workflow` / `inject_hint` /
`cancel_workflow` / `get_workflow_progress` work end-to-end, and child
workflow lifecycle events (启动 / 终态报告) already flow back to the parent
thread as system messages. Phase 2 adds the missing piece: a UI surface for
**workflows that are currently running**, so the user doesn't have to ask
the LLM "is it done yet?".

---

## 1. 目标

- 用户在 chat 里启动一个 workflow 后,**立刻**能在 UI 上看到它在跑
- 多个 workflow 并行时,各有独立的进度可见
- 进行中可一键取消
- 在别的 chat thread 启动的 workflow,完成时能在导航栏被注意到
- 切 chat thread 时,widget 内容跟着切,信息不串

## 2. 非目标

- 不在 widget 里显示完整 LangGraph stream(stream 已经能在 child thread 自己的页面看;widget 只是仪表盘)
- 不持久化"未读"状态 — 浏览器刷新即清(C-7)
- 不做跨设备同步 — 单浏览器会话语义就够
- 不做事件总线 / WebSocket 推送 — 轮询足够,Phase 2 不引入新基建
- 不为非当前 thread 的 workflow 显示进度细节 — 只用红点提醒

## 3. 总体策略 — Three Layers, No Overlap

Workflow 的视觉存在分三层,**互不重复**:

| 层 | 内容 | 来自 |
|---|---|---|
| Chat 流 | 启动通知 + 终态报告(成功/失败/取消) | Phase 1:`start_workflow` ToolMessage + 后端 `_emit_to_parent_thread` |
| Widget(nav 底部) | 进行中 workflow 的实时仪表盘 | 本 spec |
| LLM 工具 | `get_workflow_progress` 问答通道 | Phase 1 |

Phase 1 已经把"启动"和"终态"两个**事件性**节点写进了 chat 流(它们值得作为对话历史留痕)。本 spec 只补"进行中"这个**状态性**视图,放在固定位置(nav 底部),终态后从 widget 自动消失,避免与 chat 流的终态消息重复。

## 4. 位置:Workspace Nav 底部

`frontend/src/components/workspace/workspace-sidebar.tsx`(及其下属
`workspace-nav-chat-list.tsx`)是左侧 workspace 导航栏。Phase 2 在这一栏的
**底部**追加一个新区:

```
┌─ Workspace Sidebar ──────────┐
│ [logo / nav menu]            │
│                              │
│ ── Chats ──                  │
│  • Thread A      🔴          │  ← 红点:别的 thread 有终态未读
│  • Thread B      (current)   │
│  • Thread C                  │
│  • ...                       │
│                              │
│ ── Active workflows (2) ──   │  ← 仅当前 thread 的进行中
│  • demo-flow         [×]     │
│    round 5/10  ▓▓▓▓▓░░░░░    │
│  • yolo-explore      [×]     │
│    round 12 (no max)         │
└──────────────────────────────┘
```

为什么放这里:
- 跟 chat 列表同栏,"切 thread 看红点" + "看进行中 workflow" 信息密度统一
- 不动 chat-box 主区(已有 chat / artifacts 两栏布局),避免再增第三栏
- 移动端如果 nav 是抽屉,workflow 区一并跟随,不需要额外适配

## 5. Widget 内容形态

### 5.1 列表项

每条 active workflow 显示:

```
• <workflow-name>                              [×]
  <progress-line>
```

- **workflow-name**:从 `child_workflow_threads` metadata 取 `name`(如 `demo-flow`)
- **进度行**:由后端返回的 `progress_fields` 组成
  - 优先组合:`current_round` / `max_rounds` → 渲染数字 + 进度条
  - 仅 `current_round`(无 max)→ 渲染 `round N`,无进度条
  - 都没有 → 渲染 `running`,无进度条
- **`[×]` 按钮**:调 `cancel_workflow(thread_id)` LLM 工具(走和 LLM 一样的 HTTP 路径,详见 §7.2)

进度字段是平台保留约定:具体每个 workflow 申报哪些 progress_fields,在 yaml registry 里声明(Phase 1 已留好接口)。本 spec 不强制具体字段名;widget 容错处理。

### 5.2 点击条目 → 客户端本地消息

点击列表项(不是 `[×]`)→ 在当前 chat 流里**追加一条客户端本地消息**(不写进 thread state),内容是该 workflow 完整 progress JSON:

```
[Workflow demo-flow @ <child_tid>]
  current_round: 5
  max_rounds: 10
  _hints: ["focus on epoch 3"]
  history: [...]
```

实现细节:复用现有 messages 渲染管线,但消息源是前端构造,不进 LangGraph state。退出 thread / 刷新即丢。

为什么不跳页面:用户大概率不需要看 LangGraph 节点级 stream,只想确认"它在做什么"。一条客户端消息够了,不打断当前对话。

### 5.3 Widget 何时出现 / 消失

- 进入一个 chat thread → 拉一次 active workflows,有则渲染,无则区段隐藏
- 轮询发现某 workflow `is_done=true` → 从 widget 移除(终态报告已经回流到 chat 流;widget 不显示终态)
- 切 chat thread → 重新拉

## 6. 跨 thread 红点

### 6.1 行为

- 当前 thread 之外的某 thread 的 workflow 进入终态(done / failed / cancelled)→ nav 那条 thread 项上出红点
- 用户点进那个 thread → 红点清除
- 浏览器刷新 → 所有红点清除(session-only 语义,见 §7.4)
- 进行中状态**不**点亮红点 — 红点只代表"未读的终态"

### 6.2 数据基础

后端在 child workflow 进入终态时,把时戳写进 parent thread metadata
(详见 §7.3)。chat 列表 API 已经返回 `metadata: dict`,前端从
`thread.metadata.recent_workflow_finish_at` 读 ISO timestamp(或空)。
取该 thread 所有 child workflow 终态时间的**最大值**。

前端比对:

```ts
hasUnreadFinish = (
  recent_workflow_finish_at !== null &&
  Date.parse(recent_workflow_finish_at) > (lastViewedAt[threadId] ?? 0)
)
```

`lastViewedAt[threadId]` 在前端内存(详见 §7.4)。

## 7. 实现细节

### 7.1 后端:新端点 `GET /threads/{tid}/workflows/active`

**路径**:`backend/app/gateway/routers/threads.py` 追加。

**返回**:
```json
{
  "active": [
    {
      "thread_id": "<child_tid>",
      "name": "demo-flow",
      "started_at": "2026-04-28T12:00:00Z",
      "is_done": false,
      "_error": null,
      "progress": { "current_round": 5, "max_rounds": 10 }
    }
  ]
}
```

**实现**:
1. 从 parent thread metadata 读 `child_workflow_threads`(已存在)
2. 对每个 child,`checkpointer.aget(...)` 拿最新 state
3. 过滤 `is_done == true` 的(终态不显示在 widget)
4. 投影 `progress_fields` 白名单(spec §3 / Phase 1 已定义)

**性能**:N 个 children 的 `aget` 并发执行(`asyncio.gather`)。典型 N ≤ 5,sqlite checkpointer 每次 ~1ms,总耗时 < 10ms。前端 2s 轮询完全够。

**兜底**:任何 child state 取不到 / 损坏 → 跳过该条,不让一个坏 child 拖死整个端点。

### 7.2 后端:取消的 HTTP 路径

`cancel_workflow` 已经是 LLM 工具(纯 Python 函数)。Widget 取消按钮需要 HTTP 触发。两个选项:

**方案 A**:把 `cancel_workflow` 包成 HTTP 端点 `POST /threads/{tid}/workflows/{child_tid}/cancel`,内部直接调函数。
**方案 B**:前端塞个内部 `tool-call` 走现有 `runs/stream`。

选 A — workflow 取消是用户动作,不该经过 LLM thinking。直接 HTTP。

`POST .../cancel` 内部:
```python
# 复用 cancel_workflow tool 的实现核心,但脱掉 LangGraph tool 包装
await _cancel_child_workflow(parent_tid, child_tid)
```

返回 `{ok: true}` 或 `{ok: false, reason: "..."}`(child 不存在 / 已终态 / 不属于 parent 等)。

### 7.3 后端:终态时戳记 parent metadata

修改 `backend/packages/harness/deerflow/workflows/background.py` 的成功/失败/取消路径,在 emit 之后(或之前,顺序无所谓,只要原子性即可)往 parent thread metadata 写:

```python
recent = parent_meta.get("recent_workflow_finish_at")
now_iso = datetime.now(UTC).isoformat()
if recent is None or now_iso > recent:
    parent_meta["recent_workflow_finish_at"] = now_iso
```

走 langgraph 标准 `aupdate_state(... metadata=...)` 或直接走 store。**注意**:Phase 1 的 `_emit_to_parent_thread` 用 ThreadState noop graph 写 message,metadata 是单独维度,可在 emit 之后追加一次 `aupdate_state` 仅更新 metadata。或者在同一次 update 里一并写。

实现时注意:Phase 1 `_wait_for_parent_idle` 已经处理了 race,这里复用同一个时序窗口,emit 和 metadata 一起写。

### 7.4 后端:chat 列表端点扩展

`POST /threads/search`(`backend/app/gateway/routers/threads.py:349`)的
`ThreadResponse` 已经包含 `metadata: dict`。`recent_workflow_finish_at`
直接放在 metadata 里,**不需要新字段**:

```ts
type ThreadResponse = {
  thread_id: string
  metadata: {
    child_workflow_threads?: Array<{...}>
    recent_workflow_finish_at?: string  // 新增
    // ... 其他既有字段
  }
}
```

前端从 `thread.metadata.recent_workflow_finish_at` 读。**零后端结构改动**(只是 §7.3 的写入路径加这个 key)。

### 7.5 前端:`useActiveWorkflows(threadId)` hook

`frontend/src/core/workflows/hooks.ts`(新建模块)。

```ts
function useActiveWorkflows(threadId: string | null) {
  // SWR / React Query 轮询 GET /threads/{tid}/workflows/active
  // refetchInterval: 2000ms
  // pause: threadId === null
  // returns: { active: WorkflowProgressItem[], isLoading, error }
}
```

切 thread → SWR 自动按新 key 重新订阅,旧 key 停轮询。

### 7.6 前端:`ActiveWorkflowsPanel` 组件

`frontend/src/components/workspace/active-workflows-panel/index.tsx`。

- 调 `useActiveWorkflows(currentThreadId)`
- 0 条 → 整个区段不渲染(连标题也不出)
- N 条 → 渲染标题 `Active workflows (N)` + 列表
- 取消按钮:点击 → `POST .../cancel` → 乐观更新(立即从列表移除),后端确认后 SWR 一次刷新
- 列表项点击 → 调用现有 chat 上下文,在当前 thread 的本地消息流追加一条 progress JSON 消息

挂在 `workspace-sidebar.tsx` 底部。

### 7.7 前端:跨 thread 红点

修改 `frontend/src/components/workspace/workspace-nav-chat-list.tsx`:

- 维护内存里的 `lastViewedAt: Record<threadId, epochMs>`,放在 React Context 或 Zustand store(项目里有 `core/settings/store.ts` 这种 zustand 模式,沿用)
- 切到某 thread 时(路由变化或显式点击)→ `lastViewedAt[threadId] = Date.now()`
- 渲染每条 thread 项时,比较 `metadata.recent_workflow_finish_at` 与 `lastViewedAt[threadId]`,大于则渲染红点

刷新页面 → store 不持久化(默认行为)→ 红点全清(C-7 语义)。

### 7.8 前端:进度行渲染

`frontend/src/components/workspace/active-workflows-panel/progress-line.tsx`(或 inline):

```tsx
function ProgressLine({ progress }: { progress: Record<string, unknown> }) {
  const cur = progress.current_round
  const max = progress.max_rounds
  if (typeof cur === "number" && typeof max === "number") {
    return <Bar value={cur} max={max} label={`round ${cur}/${max}`} />
  }
  if (typeof cur === "number") {
    return <span>round {cur}</span>
  }
  return <span className="text-muted-foreground">running</span>
}
```

容错:任何字段缺失或类型不对 → 降级。

## 8. 文件结构

### 新建

```
backend/app/gateway/routers/
  threads.py                      # +GET /threads/{tid}/workflows/active
                                  # +POST /threads/{tid}/workflows/{cid}/cancel

frontend/src/core/workflows/
  hooks.ts                        # useActiveWorkflows
  api.ts                          # fetchActive / postCancel
  types.ts                        # WorkflowProgressItem

frontend/src/components/workspace/active-workflows-panel/
  index.tsx
  progress-line.tsx
  workflow-row.tsx

frontend/src/core/threads/
  use-thread-viewed.ts            # zustand store: lastViewedAt[threadId]

backend/tests/
  test_workflows_active_endpoint.py
  test_workflows_cancel_endpoint.py
  test_workflows_metadata_finish_stamp.py
```

### 修改

```
backend/packages/harness/deerflow/workflows/background.py
  在成功/失败/取消路径写 parent.metadata.recent_workflow_finish_at

frontend/src/components/workspace/workspace-sidebar.tsx
  挂载 ActiveWorkflowsPanel

frontend/src/components/workspace/workspace-nav-chat-list.tsx
  渲染红点(对比 metadata.recent_workflow_finish_at vs lastViewedAt)
  路由切换时调 markViewed(threadId)
```

### 删除

无。

## 9. 测试策略

### 后端

- `test_workflows_active_endpoint`:启动两个 demo-flow,assert `GET .../active` 返回两条;让一条进入终态,assert 返回一条;一条 cancel,assert 返回零条
- `test_workflows_cancel_endpoint`:HTTP cancel 后,child state `_error="..."` + `is_done=True`,parent metadata 也有时戳
- `test_workflows_metadata_finish_stamp`:成功 / 失败 / 取消 三个路径都要写 `recent_workflow_finish_at`,且单调递增

### 前端

复用现有 React Testing Library + msw 模式(项目里如果没有 msw 就用 vitest mock):

- `useActiveWorkflows` 在 threadId 切换时取消旧轮询、起新轮询
- `ActiveWorkflowsPanel` 在 0 条时不渲染、有条时渲染、点 `[×]` 调 API、点 row 触发本地消息回调
- `ProgressLine` 三种 fallback 都对
- 红点逻辑:thread.metadata.recent_workflow_finish_at vs lastViewedAt 比较(单元测试纯函数)

### 端到端

手工:
1. `make dev`
2. chat thread A 启动 demo-flow → widget 出现 row,进度更新
3. 切到 thread B → widget 空;A 的 demo-flow 跑完 → nav 上 A 项出红点
4. 点回 A → 红点清,chat 流里有 emit 终态消息,widget 重新计算无 active
5. thread A 同时启动两个 workflow → widget 两条;cancel 一条 → 该条秒级消失
6. 刷新页面 → 红点全清(进行中的 widget 重新出现 — 后端数据驱动)

## 10. 风险与权衡

| 风险 | 缓解 |
|---|---|
| 2s 轮询打 N 个 thread → 后端压力 | 单 thread 内聚合返回,不是 per-child 端点;实测 < 10ms,2s 间隔无压力 |
| Widget 显示和 chat 流终态消息时间差 | 本来就是不同语义层(widget=进行中,chat=终态留痕);可接受 |
| 用户切 thread 太快导致红点闪 | 路由切换 debounce 已有,markViewed 延迟一帧执行即可 |
| `recent_workflow_finish_at` 写失败 | 不阻塞 emit;失败仅丢失红点提示,emit 终态消息仍生效 |
| 进行中 widget 卡死(后端不再前进)| 红点机制不解决 orphaned;Phase 1 spec §8.3 明示生产前接 task queue 才解决,本 widget 不补 |
| 多 user 场景 | 现有 chat 列表已经按 user 过滤;widget 端点继承同样的鉴权,无新攻击面 |

## 11. 落地分阶段(给 plan 阶段参考)

预计两批可独立交付:

**Batch A — 后端**
- `GET /threads/{tid}/workflows/active` 端点
- `POST .../workflows/{cid}/cancel` 端点
- `background.py` 写 `recent_workflow_finish_at`
- 三个测试文件
- 验收:用 curl 能拉到进行中 workflow 列表;手工 cancel 生效;终态后 metadata 有时戳

**Batch B — 前端**
- `useActiveWorkflows` hook + 轮询
- `ActiveWorkflowsPanel` + 子组件
- nav 红点逻辑 + zustand store
- 端到端手工烟雾(§9.端到端)
- 验收:Active workflows 区在 nav 底部出现,进度滚动,cancel 工作,跨 thread 红点工作

## 12. Open Questions(给 plan 阶段)

- chat 列表当前刷新策略是什么?如果是**手动刷新**(不轮询),则跨 thread 红点不会自动出现 — 用户得切到那个 thread 才看到。要不要给 chat 列表也加 ~10s 轮询?(倾向:沿用现有刷新策略,不为这个特性单独加。Phase 2 可不解决,记入后续。)
- `progress_fields` 在 yaml registry 里的具体形态?Phase 1 实现里查一下、本 spec 假设 list[str] 字段名白名单 — plan 阶段对齐
- 客户端本地消息(§5.2)用现有 messages context 直接 push 还是另起 ephemeral channel?plan 阶段决定,影响 ~50 行
- 路由检测"切到了哪个 thread"的具体 hook(`usePathname` 还是 thread context)— plan 阶段确认,不影响设计
