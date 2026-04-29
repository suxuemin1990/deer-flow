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

## Bugs found in re-run (2026-04-29 afternoon) — fixed in plan 2026-04-29-workflow-detail-page-fixes

5. ✓ **FIXED — Injection during a *running* workflow loses the
   HumanMessage.** (Confirmed cause: SQLite checkpointer + concurrent
   `aupdate_state` race; running pregel commits checkpoint based on
   in-memory channel view, overwriting the inject.)
   **Fix**: routed running-time inject through process-local
   `hints_inbox`; the running task's loop node drains it and emits
   HumanMessage via node return so `add_messages` reducer merges into
   the next checkpoint without race. Terminal-state inject still uses
   `aupdate_state` (no race because no running task).
   - hints_inbox restored as side-channel (commit `04076160`)
   - inject_user_message_to_workflow branches on _BG_TASKS (commit `5ec964a7`)
   - Frontend optimistic pending bubble (commit `937df654`)
   Verified end-to-end on AsyncSqliteSaver via
   `tests/test_inject_during_running_workflow.py` and live browser smoke.

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
- ☑ **D14** 输入框输入 + Enter 发送 — textarea 清空,pending 乐观气泡
  立即出现(`opacity-60` + `sending…`),工作流下一 tick drain inbox
  写入 messages,polled state 同步后 pending 气泡自动消失
- ☑ **D15** user 气泡出现 + ack — 通过 hints_inbox 路由,running 期间
  注入不再丢失。**Bug 5 已修复**(commit `5ec964a7`)
- ☑ **D16** ✓✓ 在 demo-flow 上可达 — 注入在 round 4 进入 inbox,下一
  round drain 后写入 state 时再次出现在 hits/messages,polled state
  catches up,ack 自动升级到 ✓✓ (`ackFor` 看到后续 messages → consumed)
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

## L. Progress Timeline (新增,2026-04-29-workflow-detail-page-fixes)

- ☑ **L40** 详情页 PROGRESS 区域显示,标题灰色 uppercase
- ☑ **L41** 每条 history 一行 row,左侧 dot(最新 filled,older hollow)
- ☑ **L42** Row 渲染 scalar k=v(`round=N · score=0.X`),用 ` · ` 连接
- ☑ **L43** Hint 条目以 `💬 <text>` 渲染(实测 `round=4 · 💬 请加大探索强度`)
- ☑ **L44** Container `max-h-[40vh]` overflow 滚动;新条目 autoscroll 到底
- ☑ **L45** Workflow 没声明 `progress_timeline_fields` 时不渲染本区(`null` 早返)
- ☑ **L46** 6 个组件单元测试全过(test/unit/components/workspace/workflows)

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

✅ **核心路径全部通过**(A → B → C → D → F → G → I → J → K → L)。
✅ **Bug 5 已修复**(commits `04076160`/`5ec964a7`/`937df654`);bidirectional
  chat 在 running 状态下可用 — D14/D15/D16 全部 ☑。
✅ **5 个 smoke bugs 全部修复并附回归测试**(round-1 4 + Bug 5)。
✅ **Progress Timeline 落地**(plan 2026-04-29-workflow-detail-page-fixes 完成 7 个 task)。
✅ **后端 2250 测试全 pass + 3 skipped**;**前端 34/34 + typecheck + lint clean**。

## 后续可选 polish

1. **Progress timeline 高级展示** —— 当前用 `key=value` 文本拼接,可视化
   增强(分数趋势图/热力图)是后续选项,demo-flow 当前需求不强。
2. **真 LLM 工作流 smoke fixture** —— 当前 demo-flow 太纯算节点,
   不能反映带 LLM 的 workflow 行为(尤其是 ack 机制在带 LLM workflow 上的体感)。
3. **Markdown 渲染** —— summary `<pre>` → `MarkdownContent` 组件。
4. **UI 文案 i18n** —— "PROGRESS" / "sending…" / "No messages yet." 等
   英文字符串与周边中文 UI 不一致,后续 i18n 时统一。
5. **多 worker 部署支持** —— 当前 `_BG_TASKS` 是单进程内存表,多 worker
   时跨进程注入会路由错。`emit.py` docstring 已标注;若上线多 worker
   需改成 Redis pub-sub 或类似机制。
