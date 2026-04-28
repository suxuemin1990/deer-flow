# Custom Workflow Agent Platform — Design

**Status**: Draft (brainstormed 2026-04-28)
**Predecessor**: `docs/superpowers/plans/2026-04-27-demo-flow-mode-b.md` (demo_flow B 形态),验证了"双 thread + 共享 checkpointer + 工具触发"的可行性。本 spec 把那次验证的成果产品化为通用平台。

---

## 1. 目标

让任何人能写一个 LangGraph 工作流图,通过一份 yaml 注册到 deerflow,自动获得:

- lead_agent 通过统一工具 `start_workflow(name, params)` 启动它(后台异步,立即返回 thread_id)
- 后台执行,共享 gateway checkpointer,可独立查询 state
- chat 端可通过 `inject_hint` 工具向运行中的 workflow 注入自由文本提示(非阻塞,丢失允许)
- 跑完报告自动回写到父 chat thread;失败也回写
- 前端在 chat 中实时看到子 workflow 的进度(child workflow widget)
- 用户可主动取消运行中的 workflow

## 2. 非目标

明确不在本期范围内:

- 任务持久化跨 gateway 重启(`asyncio.create_task` 本进程,重启即丢)
- 多用户隔离 / 配额 / 速率限制
- workflow 互相调用形成 DAG
- workflow state schema migration
- 自由文本以外的注入形态(action / 结构化命令)
- workflow 注册的可视化管理 UI

## 3. 注册形态(yaml 驱动)

deerflow 启动时扫描配置加载 workflow 注册表。每个 workflow 一项:

```yaml
workflows:
  - name: yolo-explore
    description: |
      YOLO 系列模型的超参数自动探索。给定源码路径和监控指标,
      多轮调整学习率/batch_size 等并对比得分。
    factory: deerflow.workflows.yolo:make_graph
    input_schema: deerflow.workflows.yolo:YoloExploreInput
    done_field: is_done
    report_field: report_markdown
    progress_fields: [current_round, max_rounds, history]
    hint_behavior_doc: |
      Hints are consumed at the start of each round and biases hyperparameter
      selection. Multiple hints accumulate; older hints stay until the
      workflow chooses to clear them.
```

字段语义:

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 唯一标识,kebab-case |
| `description` | ✅ | 写给 LLM 看的功能简介,会注入 lead_agent system prompt |
| `factory` | ✅ | `module:callable` — 调用签名 `(checkpointer) -> CompiledGraph` |
| `input_schema` | ✅ | `module:Class` — Pydantic BaseModel,字段名必须英文 |
| `done_field` | ✅ | state 中判断"完成"的布尔字段名 |
| `report_field` | ✅ | 完成时往父 thread 写哪个字段(markdown/text) |
| `progress_fields` | ❌ | `get_workflow_progress` 返回的展示字段白名单;不声明则只返回平台字段 |
| `hint_behavior_doc` | ❌ | 写给 LLM 看的"这个 workflow 怎么消费 hint"说明,注入 system prompt |

加载策略:

- yaml 解析 + factory/input_schema **eager-import**,失败的条目跳过 + log error,不拖死 gateway 启动
- `/health` 暴露 `workflows: {loaded: [...], failed: [{name, reason}]}`

## 4. 入参契约(Pydantic + 强制英文)

`input_schema` 必须是 Pydantic BaseModel,所有字段名英文。中文只能出现在 `Field(description=...)`、docstring、报告内容里。

```python
# deerflow/workflows/yolo/__init__.py
from pydantic import BaseModel, Field

class YoloExploreInput(BaseModel):
    task_name: str = Field(description="人类可读的任务名")
    max_rounds: int = Field(default=10, ge=1, le=50, description="最大探索轮次")
    target_metric: str = Field(default="mAP_0.5", description="主监控指标")
```

`start_workflow` 工具运行时用 `model_validate` 校验,失败返回 `ToolMessage` 给 LLM,LLM 自然向用户追问缺失字段(无需 strict/soft/heuristic 模式区分 — 由字段是否 Optional 自然表达)。

## 5. 平台 State 契约

所有 workflow 的 state 必须包含平台保留字段。提供基类供组合:

```python
# deerflow/workflows/base_state.py
from typing import Annotated, NotRequired, TypedDict

def _hints_reducer(existing: list[str] | None, new: list[str] | None) -> list[str]:
    if new is None:
        return existing or []
    if new == []:           # 显式清空
        return []
    return (existing or []) + new   # 默认追加

class WorkflowBaseState(TypedDict, total=False):
    _parent_thread_id: str
    _hints: Annotated[list[str], _hints_reducer]
    _error: str | None
```

作者的 state 推荐写法:

```python
class YoloExploreState(WorkflowBaseState):
    task_name: str
    max_rounds: int
    current_round: NotRequired[int]
    history: Annotated[list[dict], _merge_list]
    report_markdown: NotRequired[str]
    is_done: NotRequired[bool]
```

`done_field` / `report_field` / `progress_fields` 都是作者业务字段,平台不强制名字,只要 yaml 声明即可。

## 6. Hint 注入(非阻塞 inbox)

- **字段名**:`_hints`(下划线前缀 = 平台字段)
- **类型**:`list[str]`
- **reducer**:append + 显式 `[]` 清空
- **读责任**:作者在自己的节点里 `state.get("_hints", [])`,自行决定何时读、怎么用、是否清空
- **平台不提供 helper**:语义因 agent 而异(拼 system prompt / 当 user message / 当 tool result),平台不预设
- **读完清空**:作者节点 return `{"_hints": []}` 即可
- **写入路径**:用户 → `inject_hint` 工具 → `graph.update_state(thread_id, {"_hints": [hint]})`
- **丢失允许**:用户输入若节点未读到即丢,不阻塞流程

## 7. 报告 / 进度回流

### 7.1 启动:父 → 子关系建立

`start_workflow` 工具行为:

1. 校验 `name` 在 registry,否则 `ToolMessage` 错误
2. `registry[name].input_schema.model_validate(params)` — 失败 `ToolMessage` 错误
3. 生成新 `child_thread_id = uuid4()`
4. 从 `ToolRuntime.context["thread_id"]` 取父 chat thread_id
5. 把 `child_thread_id` 追加到父 thread 的 metadata 字段 `child_workflow_threads: list[{thread_id, name, started_at}]`
6. `asyncio.create_task(_run_workflow_background(...))`,task 保存在 `_BG_TASKS` 集合防 GC
7. 返回 `Command(update={"messages": [ToolMessage(f"已启动 {name}, thread_id={child_thread_id}")]})`

### 7.2 中途进度(C2 — 前端 widget)

**Backend**:
- 子 thread 复用 LangGraph 现有 `/threads/{tid}/runs/stream` 端点(无需新增)
- 新增 `GET /threads/{tid}/children` → `[{thread_id, name, started_at, is_done}]`(从父 thread metadata 读)
- 新增 LLM 工具 `get_workflow_progress(thread_id)` — 返回平台字段 + `progress_fields` 白名单字段;LLM/用户主动问也能用,作为前端 widget 的备用通道

**Frontend**:
- 新增 `useChildWorkflows(parent_thread_id)`:打 `/threads/{tid}/children` + 对每个子 thread 订阅 stream
- 新增 child workflow widget(UX 形态在 plan 阶段定稿,候选见 §11)
- chat thread 切换时重新拉 children

### 7.3 终态报告(成功)

`_run_workflow_background` 在 `graph.ainvoke(...)` 正常返回后:

```python
final_state = await graph.aget_state(config={"configurable": {"thread_id": child_tid}})
if final_state.values.get(spec.report_field):
    report = final_state.values[spec.report_field]
    parent_tid = final_state.values.get("_parent_thread_id")
    if parent_tid:
        await _emit_to_parent_thread(
            parent_tid,
            f"[workflow:{name}] 完成\n\n{report}",
            checkpointer=cp,
        )
```

`_emit_to_parent_thread` 用 langgraph 标准 API 把 system message append 到父 thread state 的 `messages`,**不绕路自己写 SQL**。

### 7.4 失败报告

`_run_workflow_background` 的 `except`:

```python
except Exception as e:
    err = f"{type(e).__name__}: {e}"
    try:
        await graph.aupdate_state(
            config={"configurable": {"thread_id": child_tid}},
            values={"_error": err, spec.done_field: True},
        )
    finally:
        if parent_tid:
            await _emit_to_parent_thread(
                parent_tid,
                f"[workflow:{name}] 失败: {err}",
                checkpointer=cp,
            )
    logger.exception("workflow %s failed: %s", name, child_tid)
```

无论 update_state 是否成功,只要拿到 parent_tid 就尝试 emit。父 thread emit 失败不再升级 — 已经 logger.exception 一次,够了。

## 8. 取消 / 错误 / 生命周期

### 8.1 取消

LLM 工具 `cancel_workflow(thread_id)`:

1. 校验 thread_id 是注册过的 workflow(从父 thread metadata 反查)
2. 找到对应的 background task(`_BG_TASKS` 用 `child_thread_id → task` 映射)
3. `task.cancel()` — 抛 CancelledError 中断当前节点
4. `update_state` 写 `_error="cancelled by user"` + `done_field=True`
5. emit 一条 system message 到父 thread

接受:节点跑到一半被 cancel 可能 checkpoint 不一致。LangGraph checkpoint 节点级 atomic 兜底,从上一个 checkpoint 恢复,行为可定义。

### 8.2 异常

见 §7.4。

### 8.3 重启

**不实现 task 持久化**。文档明示:

> gateway 重启 = 进程内 `asyncio.create_task` 全部丢失。已经写入 checkpointer 的 state 完整保留,但不会再前进。前端 widget 看到 `is_done=false` 但长时间无新 stream 事件 → 视为 orphaned。
>
> 生产环境必须接外部 task queue(Celery / Arq / RQ)来保证持久性,本平台第一版只服务于单进程开发场景。

`get_workflow_progress` 可选返回 `seconds_since_last_checkpoint`,前端可据此提示"可能已 orphaned"(P2,首版不必)。

## 9. 公开 API 总览

### LLM 工具(暴露给 lead_agent)

固定 4 个,**不随 workflow 数量增长**:

| 工具 | 签名 | 说明 |
|---|---|---|
| `start_workflow` | `(name: str, params: dict) -> str` | 启动注册的 workflow,返回 child_thread_id |
| `inject_hint` | `(thread_id: str, hint: str) -> str` | 往运行中的 workflow 写 hint |
| `cancel_workflow` | `(thread_id: str) -> str` | 取消运行中的 workflow |
| `get_workflow_progress` | `(thread_id: str) -> dict` | 查询进度(平台字段 + `progress_fields`) |

`inject_hint` / `cancel_workflow` / `get_workflow_progress` 都校验 thread_id 必须是注册 workflow,防止误注入到 chat thread。

### lead_agent system prompt 注入

registry 启动时渲染 workflow 目录,作为 lead_agent system prompt 的一节(deerflow SOUL.md 同款机制):

```
## Available Workflows

You can start long-running workflows via start_workflow(name, params).
Use inject_hint / cancel_workflow / get_workflow_progress to control them.

### yolo-explore — YOLO 超参自动探索
Params (validate against this schema, ask user for missing required fields):
  - task_name (str, required): 人类可读的任务名
  - max_rounds (int, default=10): 最大探索轮次
  - target_metric (str, default="mAP_0.5"): 主监控指标
Hint behavior: Hints are consumed at the start of each round and biases
hyperparameter selection.

### demo-flow — ...
```

参数表由 Pydantic schema 自动生成。`hint_behavior_doc` 直接拼接。

### HTTP API(给前端)

| 端点 | 状态 | 说明 |
|---|---|---|
| `GET/POST /threads/...` | 已有 | LangGraph 标准 |
| `POST /threads/{tid}/runs/stream` | 已有 | LangGraph 标准,前端订阅子 thread |
| `GET /threads/{tid}/children` | **新增** | 列出该 thread 启动的所有子 workflow thread |

## 10. 文件结构

### 新建

```
backend/packages/harness/deerflow/workflows/
  __init__.py
  base_state.py          # WorkflowBaseState + _hints_reducer
  registry.py            # yaml 加载、WorkflowSpec dataclass、查找
  tools.py               # start_workflow / inject_hint / cancel_workflow / get_workflow_progress
  background.py          # _run_workflow_background helper(成功 emit / 失败 emit)
  emit.py                # _emit_to_parent_thread(用 langgraph 标准 API)
  prompt.py              # 渲染 workflow 目录 → system prompt 片段
  demo_flow/             # 第一个示例 workflow,从现 agents/demo_flow 迁入
    __init__.py          # factory: make_graph(checkpointer)
    schema.py            # DemoFlowInput (Pydantic)
    state.py
    agent.py
    nodes/...

backend/config/workflows/
  demo_flow.yaml         # 平台示例
  # yolo_explore.yaml    # 后续

backend/tests/
  test_workflows_registry.py
  test_workflows_tools.py
  test_workflows_background_emit.py
  test_workflows_demo_flow.py     # 端到端

frontend/src/core/threads/
  use-child-workflows.ts          # 父 thread 拉 children + 多 stream 订阅

frontend/src/components/workspace/child-workflow-widget/
  index.tsx                       # UX 形态在 plan 阶段定稿
```

### 修改

```
backend/app/gateway/deps.py
  lifespan 里 WorkflowRegistry.load() + set_default_checkpointer (已有)

backend/app/gateway/routers/threads.py
  新增 GET /threads/{tid}/children

backend/packages/harness/deerflow/tools/tools.py
  BUILTIN_TOOLS 加入 4 个平台工具(替代当前手写的 start_demo_exploration)

backend/packages/harness/deerflow/agents/lead_agent/...
  system prompt 启动时拼上 registry.render_prompt_section()
```

### 删除

```
backend/packages/harness/deerflow/tools/builtins/demo_flow_tool.py
  被 start_workflow 单工具替代

backend/packages/harness/deerflow/agents/demo_flow/
  迁入 workflows/demo_flow/(本体保留,仅位置变化)
```

## 11. 风险与权衡

| 风险 | 缓解 |
|---|---|
| `task.cancel()` 中间状态不一致 | LangGraph checkpoint 节点级 atomic 兜底;文档提示作者节点应做最小化 IO |
| Gateway 重启丢任务 | 文档明示;生产前必须接 task queue;前端 widget 用 `seconds_since_last_checkpoint` 提示 orphaned(P2) |
| 跨 thread 写 message | 统一走 `_emit_to_parent_thread` helper,内部用 langgraph 标准 API,绝不绕路自己 SQL |
| LLM 给错 thread_id | 4 个 thread 操作工具全部校验 thread_id 必须是注册 workflow |
| Workflow 加载失败拖死 gateway | yaml 加载 try/except per item,失败跳过 + log + `/health` 暴露 |
| lead_agent system prompt 膨胀 | workflow 描述短(description + params 一行 + hint_behavior 一段);随 N 个 workflow 线性,但每条 prompt cache 命中 |
| Pydantic schema dict 透传可能丢类型 | `start_workflow` 工具用 `model_validate(params)` 校验后再传给 graph,失败 ToolMessage 反问 |
| `demo_flow` 的归宿 | 迁入 `workflows/demo_flow/` 作为"零 LLM workflow 也能跑"的平台示例;不删 |

## 12. Child Workflow Widget UX(待 plan 阶段定稿)

候选三种,plan 阶段独立 brainstorm:

**A. 内嵌折叠卡片**:启动 workflow 时在 chat 流里插入一张卡片,默认折叠显示标题+进度;展开看 stream
- 优点:跟当前对话强绑定,上下文自然
- 缺点:多个 workflow 同时跑会挤占 chat 流

**B. 侧边栏面板**:右侧固定栏,列出当前 chat thread 的所有 child workflow,各有进度条 + 完成/失败标签
- 优点:不打扰 chat 主流;多 workflow 友好
- 缺点:占屏宽,移动端不友好

**C. 浮窗**:右下角悬浮小卡片,可关闭/重开;展开看详情
- 优点:不抢空间,可隐藏
- 缺点:多个 workflow 重叠

倾向 B。但需要 plan 阶段确认。

## 13. 落地分阶段(给 plan 阶段参考)

预计 3 阶段,每阶段独立可交付:

**Phase 1 — Backend 平台底座**(本 spec 全 backend 内容)
- workflows/ 包(base_state / registry / tools / background / emit / prompt)
- demo_flow 迁入
- 4 个 LLM 工具上线,lead_agent system prompt 注入 workflow 目录
- `GET /threads/{tid}/children` 端点
- 测试覆盖
- 验收:LLM 能 `start_workflow("demo-flow", {...})` 后台跑通,`inject_hint` / `cancel` / `progress` 全部生效;成功/失败终态都 emit 到父 thread

**Phase 2 — Frontend Child Workflow Widget**
- UX 形态定稿(brainstorm)
- `useChildWorkflows` hook
- widget 组件 + 集成
- 验收:用户在 chat 启动 workflow 后,UI 立即出现 widget;实时显示进度;完成/失败状态切换;切 chat thread 不串

**Phase 3 — 第一个真 workflow:training_explore 接入**
- 现有骨架 + 接 LLM + 接 compute_cli
- yaml 注册
- 端到端跑通真任务
- 验收:用户能让 lead_agent 启动一个真 yolov5 探索,中途 inject_hint 调整方向,最终拿到 markdown 报告

每阶段独立 plan,本 spec 只给方向不给步骤。

---

## Open Questions(给 plan 阶段)

1. Child workflow widget 的 UX 形态(§12)
2. `_emit_to_parent_thread` 的具体 langgraph API:用 `aupdate_state` 直接 append 到 `messages`,还是触发一个临时 run?(影响是否对前端 stream 可见)
3. `inject_hint` 工具调用对父 chat thread 的可见性:LLM 看到 ToolMessage,但用户在 chat 里要不要也看到一条 system 提示"已注入 hint"?
4. `start_workflow` 失败(校验失败)的反问 UX:工具 return ToolMessage 让 LLM 追问 vs 工具直接报错让 LLM 重组 — 推荐前者,plan 时确认
5. workflow 本身需不需要 LLM 调用?如果工作流图里有 LLM 节点,模型选择走哪个 config?(目前假设 workflow 自己决定,平台不管)
