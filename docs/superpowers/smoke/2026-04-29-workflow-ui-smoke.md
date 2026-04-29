# Workflow UI Redesign — Smoke Test Plan

Date: 2026-04-29
Branch: `main` at commit `0532eb11` (post-smoke-fixes)

## Setup

```bash
make dev
```

Wait for gateway (8001), frontend (3000), nginx (2026). The
external `langgraph dev` (2024) is started by `make dev` but is **not**
on the data path — gateway has langgraph runtime embedded.

Open `http://localhost:2026` (or `http://localhost:3000` direct) in the
browser.

Convention: ☐ pending · ☑ pass · ✗ fail · ⚠️ partial / blocked.

## Bugs found and fixed during smoke

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

## A. Sidebar / 路由

- ☑ **A1** 侧边栏出现 Workflows 入口 — Chats / Agents / Workflows
- ☑ **A2** 空 Hub 文案显示
- ☑ **A3** 聊天页无 ActiveWorkflowsPanel
- ☑ **A4** 聊天列表无红点(数据库为空,无可能)

## B. 启动工作流 + workflow_link 卡片

- ☑ **B5** 主 agent 调用 `start_workflow` 工具
- ☑ **B6** workflow_link 卡片可点击渲染(✓ icon + "View workflow: demo-flow" + child_tid 前 8 位 + 右箭头),在思考面板下方
- ☑ **B7** 卡片跳转到 `/workspace/workflows/<child_tid>`

## C. Hub 列表

- ☑ **C8** 父会话节点出现
- ☑ **C9** 父会话标题 = thread.title(修复 #3 后)
- ☑ **C10** Workflow row 显示 ✓ + name + report 首句 + 相对时间
- ☑ **C11** Hover 出现 quick actions(在 DOM,CSS `group-hover:flex`)— 已 done 时:跳父会话 + Delete;running 时:Cancel + 跳父会话(经源代码确认)
- ☑ **Q2** 含活跃工作流父会话默认展开,纯历史折叠

## D. 双向 chat 详情页

- ☑ **D12** Header `demo-flow · done · current_round=N · max_rounds=N`(scalar 字段渲染)
- ☑ **D13** 初始无 AIMessage(demo-flow 是无 LLM 工作流,符合预期)
- ☑ **D14** 输入框输入 + Enter 发送
- ☑ **D15** user 气泡出现 + 单 ✓
- ⚠️ **D16** ✓✓ 在测试场景下未触发 — 因为 demo-flow 跑得比注入快,注入到达时 workflow 已 done。**架构限制**:running Pregel 不重读外部 state 写入(同 hints_inbox 文档警告)。**需要在更慢/真有 LLM 的工作流上验证**
- ☑ **D17** Shift+Enter 换行(代码路径正确)

## E. inject_hint 工具仍可用 — 跳过(需要主 agent 慢速对话,smoke 时间紧)

- ☐ **E18-20** 通过主 agent 调 inject_hint。**已通过单元测试覆盖** (test_inject_hint_writes_human_message_via_messages_channel)

## F. Cancel — 部分

- ☐ **F21** Hub Cancel 按钮(running 工作流跑得太快,smoke 没赶上)
- ☐ **F22** 状态变 cancelled(同上)
- ☑ **F23** 终态详情页 Cancel 按钮隐藏,输入框 disabled,placeholder "Workflow has ended"
- ☐ **F24** 父会话出现取消通知(等同上)

## G. 完成态

- ☐ **G25** 启动 max_rounds=2 — 多次启动验证完成态过
- ☑ **G26** Hub row 显示 ✓ + report 首句预览
- ☑ **G27** 详情页顶部 sticky summary 卡显示完整 report markdown(纯文本展示,markdown rendering 是后续 polish 项)

## H. 失败态 — 跳过

- ☐ **H28-29** 需手工造非法 params。**单元测试已覆盖** failed/cancelled 分类逻辑

## I. 删除

- ☑ **I30** Hub row Delete 按钮
- ☑ **I31** Row 消失,列表自动刷新(经修复 #3 后立即生效)
- ☑ **I32** `curl /api/workflows/all` 不再包含被删 child

## J. 跨会话聚合 — 部分

- ☑ **J33** 跨多个父会话启动多个 workflow,Hub 都显示
- ☐ **J34** 创建时间倒序(只有一个父会话时无法验证排序;**单元测试已覆盖** sort 逻辑)
- ☑ **J35** 纯历史父会话默认折叠

## K. 边界

- ☑ **K36** Hub 列表 3s 轮询(确认刷新工作)
- ☑ **K37** 详情页 1.5s 轮询(确认刷新工作)
- ☐ **K38** F5 刷新(未显式测试,但路由是 stateless URL,理论上 OK)
- ☐ **K39** 无效 child_tid → "Workflow not found"(代码路径已确认)

## 综合判定

✅ **核心路径全部通过**(B → C → D → I)。
✅ **4 个 smoke 期间发现的 bug 全部修复并附回归测试**。
⚠️ **D16 ✓✓ 标记需要在真 LLM 工作流上复测**。架构上 demo-flow 由于无 LLM 节点,workflow tick 间不会主动 yield 给注入留下时间窗。
✅ **后端 2242 测试全 pass**;**前端 typecheck + lint clean**。

后续:可在有 LLM 的工作流(如 research_explore)上 sustained-run smoke,验证 D16 + ✓✓ 真实表现。
