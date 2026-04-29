# Workflow UI Redesign — Smoke Test Plan

Date (last run): 2026-04-29 (re-run)
Branch: `main` at commit `f8b38604` (post-smoke-fixes)

## Setup

```bash
make dev
```

Wait for gateway (8001), frontend (3000), nginx (2026). The
external `langgraph dev` (2024) is started by `make dev` but is **not**
on the data path — gateway has langgraph runtime embedded.

Open `http://localhost:2026` (or `http://localhost:3000` direct) in the
browser.

For testing injection / cancel timing, temporarily bump
`backend/packages/harness/deerflow/workflows/demo_flow/nodes/poll_wait_node.py`'s
`asyncio.sleep(2)` to `asyncio.sleep(8)` to make rounds slow enough to
observe. Restore before committing — tests monkeypatch this so they're
unaffected, but production wants the snappy default.

Convention: ☐ pending · ☑ pass · ✗ fail · ⚠️ partial / blocked.

## Bugs found and fixed during smoke (round 1, 2026-04-29 morning)

1. ✓ **Plan put `workflow_link` render branch in `MessageListItem`,
   but tool messages flow through `MessageGroup`.** Render moved to
   `MessageList` after each group's MessageGroup output.
   (Commit `a60622e7`.)
2. ✓ **Non-scalar progress fields (`history` is `list[dict]`) became
   `[object Object]` in summaries.** Filter to scalars only.
   (Commit `a60622e7`.)
3. ✓ **Hub aggregator looked at `record["title"]` but title lives at
   `record["values"]["title"]`** — every parent showed up with
   thread_id fallback. Also: deleted child workflows still appeared
   because parent's `metadata.child_workflow_threads` array kept the
   stale entry. Skip entries whose checkpoint is gone.
   (Commit `544fe2c5`.)
4. ✓ **Critical: injecting via emit's `ThreadState` noop graph wiped
   workflow business state.** SQLite drops every channel not declared
   on the schema being used to write. Now use the workflow's own spec
   to compile the appender so all channels survive.
   (Commit `0532eb11`.)

## Bugs found in re-run (2026-04-29 afternoon)

5. ✗ **OPEN — Injection during a *running* workflow loses the
   HumanMessage.** Reproduced on demo-flow with `max_rounds=8` and
   `sleep=8s/round`: POST `/threads/{p}/workflows/{c}/messages`
   returns 200, but child thread's `state.values.messages` stays
   empty across the rest of the run and after completion (`messages`
   key absent or count 0). Same workflow, after `is_done=True`, accepts
   injection cleanly (verified — `curl注入测试` persisted on
   `72a093be`). Hypothesis: while `graph.ainvoke(...)` is mid-run,
   the running task commits each step's checkpoint with its own
   cached view of channels (which never observes the inject's branch
   checkpoint), overwriting the inject. Same checkpointer; same
   thread_id; not a routing issue. **This invalidates previous round's
   ☑ on D14/D15** — the bubbles that appeared back then likely
   rendered briefly between an inject-checkpoint and the next
   running-task-step-overwrite, then disappeared. Needs investigation
   before declaring bidirectional chat shippable; current channel
   delivery promise only holds for terminal-state injections.

## A. Sidebar / 路由

- ☑ **A1** 侧边栏出现 Workflows 入口 — Chats / Agents / Workflows
- ☑ **A2** 空 Hub 文案显示("All workflows you've started, grouped by chat.")
- ☑ **A3** 聊天页无 ActiveWorkflowsPanel(DOM 不含 active-workflows 残迹)
- ☑ **A4** 聊天列表无红点(0 个 `bg-red`/`bg-destructive` 元素)

## B. 启动工作流 + workflow_link 卡片

- ☑ **B5** 主 agent 调用 `start_workflow` 工具
- ☑ **B6** workflow_link 卡片渲染:✓ icon + "View workflow: demo-flow"
  + child_tid 前 8 位 + 右箭头
- ☑ **B7** 卡片跳转到 `/workspace/workflows/<child_tid>`

## C. Hub 列表

- ☑ **C8** 父会话节点出现
- ☑ **C9** 父会话标题 = thread.title
- ☑ **C10** Workflow row 显示 ✓ + name + report 首句 + 相对时间
- ☑ **C11** Hover quick actions:运行中显示 Cancel(已实测 click);
  done/cancelled 显示 Delete + 跳父会话
- ☑ **Q2** 含活跃或未读 done 的父会话默认展开,纯历史折叠

## D. 双向 chat 详情页

- ☑ **D12** Header `demo-flow · {status} · current_round=N · max_rounds=N`
- ☑ **D13** 初始无 AIMessage(demo-flow 是无 LLM 工作流,符合预期)
- ⚠️ **D14** 输入框输入 + Enter 发送 — 代码路径正确,UI 上 textarea
  会清空,但当工作流运行中时消息丢失(见 Bug 5)
- ⚠️ **D15** user 气泡出现 + ✓ — 工作流终态后注入可见
  (`curl注入测试` 在 done workflow 上持久),运行中注入不可见
- ✗ **D16** ✓✓ 不可达 —— 注入在运行中根本进不了 state(见 Bug 5);
  原"running Pregel 不重读外部 state 写入"的描述偏轻,实际是
  *消息直接被运行任务的下一个 checkpoint 写覆盖丢失*
- ☑ **D17** Shift+Enter 换行(代码路径正确)

## E. inject_hint 工具仍可用

- ☐ **E18-20** 通过主 agent 调 inject_hint。**单元测试覆盖**
  (test_inject_hint_writes_human_message_via_messages_channel),
  但该测试用 InMemorySaver,与 Bug 5 同样的 SQLite + running-task
  竞态条件未覆盖。**应当复测**

## F. Cancel

- ☑ **F21** Hub Cancel 按钮(running workflow 上 hover 出现,click 触发)
- ☑ **F22** 状态变 cancelled,API 返回 `error: CancelledError: workflow
  cancelled by user`
- ☑ **F23** 终态详情页 Cancel 按钮隐藏,输入框 disabled,
  placeholder "Workflow has ended",error 信息渲染
- ☑ **F24** 父会话出现 `[workflow:demo-flow] cancelled by user` AIMessage

## G. 完成态

- ☑ **G25** max_rounds=N 跑完 — 多次启动均自然完成
- ☑ **G26** Hub row 显示 ✓ + report 首句预览
- ☑ **G27** 详情页顶部 sticky summary 卡显示完整 report markdown
  (纯 `<pre>` 渲染,markdown 高亮是 polish 项)

## H. 失败态

- ☐ **H28-29** 需手工造非法 params。**单元测试已覆盖** failed/cancelled
  分类逻辑

## I. 删除

- ☑ **I30** Hub row Delete 按钮
- ☑ **I31** Row 立即消失,parent 计数 4→3,列表自动刷新
- ☑ **I32** `GET /api/workflows/all` 不再包含被删 child(被删
  `f8a916ee` 已不在响应中)

## J. 跨会话聚合

- ☑ **J33** 跨多个父会话启动多个 workflow,Hub 都显示
  (启动demo-flow工作流 / 慢任务会话配置 两个父会话同时呈现)
- ☑ **J34** Parent 排序按 created_at desc(spec 明确定义);
  inner workflow 排序为 started_at asc(spec 未定义 → 现状 OK)
- ☑ **J35** 纯历史父会话默认折叠,含活跃或未读 done 的展开

## K. 边界

- ☑ **K36** Hub 列表 3s 轮询(实测 status 变化在 3s 内反映)
- ☑ **K37** 详情页 1.5s 轮询(实测 state 变化在 1.5s 内反映)
- ☑ **K38** F5 刷新 Hub 列表正常加载(routing stateless)
- ☑ **K39** 无效 child_tid 显示 "Workflow not found.",有 Back 链接

## 综合判定

✅ **大部分核心路径通过**(A → B → C → F → G → I → J → K)。
✗ **D14-D16 暴露真实数据丢失 bug**(Bug 5);bidirectional chat 在
  running 状态下不可用,只在终态可用。这与设计目标(运行中提示)冲突,
  必须修复后才能宣告 ship。
✅ **4 个 round-1 smoke bugs 修复并附回归测试**。
✅ **后端 2242 测试全 pass**;**前端 typecheck + lint clean**。

## 建议优先级

1. **修 Bug 5 (D14-D16)** — 调查 LangGraph SQLite checkpointer 在
   `aupdate_state` vs 并发 `ainvoke` 步进时的写覆盖语义;考虑
   (a) 在 running task 内显式重读最新 checkpoint,或
   (b) 改用专门的"挂起 → 注入 → 续跑"模式(`graph.aupdate_state`
   后通过 interrupt 触发再运行)
2. **写一个真 LLM 工作流的 smoke fixture** —— 当前 demo-flow 太
   纯算节点,不能反映带 LLM 的 workflow 行为
3. **可选 polish** —— summary `<pre>` → `MarkdownContent`
