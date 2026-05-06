# 类型与实体导览(Types & Entities)

> 面向第一次接触 DeerFlow 代码库的工程师。本文回答一个问题:
> **「这些 Pydantic 模型 / TypedDict / dataclass 都是干什么的,它们之间怎么串起来?」**

如果你想要更高层的部署/请求链路视角,先读 [`ARCHITECTURE.md`](ARCHITECTURE.md);本文聚焦 *领域类型*。

---

## 1. 项目一览

DeerFlow 是一个 **LangGraph + FastAPI 的「超级 Agent 调度框架」**,带 Next.js 前端。

- **会话 / 状态 / 检查点** → 交给 LangGraph(thread / run / checkpoint 协议)
- **工具执行 / 沙箱 / 技能 / MCP 扩展** → 自家 `packages/harness/deerflow/` 实现
- **REST / SSE 接口** → FastAPI Gateway(`backend/app/gateway/`),兼容 LangGraph Platform 协议,前端可直接用 `@langchain/langgraph-sdk` 的 `useStream` 对接

**部署模式**:

| 模式 | 命令 | 进程 |
|---|---|---|
| 标准开发 | `make dev` | LangGraph Server `:2024` + Gateway `:8001`(两进程) |
| Pro 开发 | `make dev-pro` | Gateway `:8001` 内嵌 LangGraph 运行时(单进程) |
| Docker | `make docker-*` | `nginx + frontend + gateway` 一体化 |

**请求链路**:

```
浏览器 → nginx :2026 → frontend (Next.js) :3000 → gateway :8001
       → LangGraph runtime(:2024 或内嵌)→ LLM / 工具 / MCP / Sandbox
```

---

## 2. 核心领域实体

### 2.1 LeadAgent — `agents/lead_agent/agent.py`

`make_lead_agent(config: RunnableConfig)` 是一切的入口。它读取 `RunnableConfig.configurable` 里的运行时参数,选模型、装中间件链,最后调用 LangChain 的:

```python
create_agent(model, tools, middleware, system_prompt, state_schema=ThreadState)
```

返回一个 LangGraph 可执行图。

**中间件链**(顺序非常重要):

| # | Middleware | 作用 |
|---|---|---|
| 1 | `ThreadDataMiddleware` | 解析 `thread_id`,挂载 `workspace_path / uploads_path / outputs_path` |
| 2 | `UploadsMiddleware` | (可选)把用户上传文件挂进沙箱,大纲注入上下文 |
| 3 | ~~`SandboxMiddleware`~~ | (removed; tools now run directly on the host) |
| 4 | `DanglingToolCallMiddleware` | 修补历史中无 `ToolMessage` 配对的 `tool_calls`,避免 LLM 报错 |
| 5 | `LLMErrorHandlingMiddleware` | 包住模型调用异常,转成可恢复的消息 |
| 6 | `GuardrailMiddleware`(可选) | 输入 / 输出合规检测 |
| 7 | ~~`SandboxAuditMiddleware`~~ | (removed) |
| 8 | `ToolErrorHandlingMiddleware` | 把工具异常转成 `ToolMessage`(否则 LLM 卡住) |
| 9 | `DeerFlowSummarizationMiddleware`(可选) | 上下文超阈值时压缩历史,对 skill 文件读取做特殊保留 |
| 10 | `TodoMiddleware`(plan 模式) | 注入 `write_todos` 工具 + 任务追踪 prompt |
| 11 | `TokenUsageMiddleware`(可选) | 统计 prompt / completion tokens |
| 12 | `TitleMiddleware` | 首轮对话后异步生成会话标题 |
| 13 | `MemoryMiddleware` | 把对话排队进长时记忆库 |
| 14 | `ViewImageMiddleware` | 模型支持 vision 时,把已查看图片注入消息 |
| 15 | `DeferredToolFilterMiddleware`(可选) | 工具搜索模式下过滤掉延迟加载的工具 schema |
| 16 | `SubagentLimitMiddleware` | 限制并发 subagent 数量 |
| 17 | `LoopDetectionMiddleware` | 检测重复工具调用循环并打断 |
| 18 | `ClarificationMiddleware`(始终最后) | 模型若返回澄清请求,在此拦截后中断 run |

> 之前文档写的"12 中间件"是默认配置下大致激活的数量;实际是**按配置开关组装**的。

### 2.2 ThreadState — `agents/thread_state.py`

整个 LangGraph 流转的「状态包」,继承 `langchain.agents.AgentState`(已含 `messages: list[BaseMessage]`)。DeerFlow 扩展字段:

| 字段 | 类型 | 含义 |
|---|---|---|
| `sandbox` | `{sandbox_id}` | 当前 thread 绑定的沙箱实例 |
| `thread_data` | `{workspace_path, uploads_path, outputs_path}` | 该 thread 的物理路径 |
| `title` | `str` | 会话标题(`TitleMiddleware` 写入) |
| `artifacts` | `Annotated[list[str], merge_artifacts]` | 累积产物路径(去重合并) |
| `todos` | `list` | `TodoMiddleware` 维护的任务列表 |
| `uploaded_files` | `list[dict]` | 上传文件清单 |
| `viewed_images` | `Annotated[dict, merge_viewed_images]` | path → {base64, mime_type},空 dict 表示清空 |

`Annotated[..., reducer]` 是 LangGraph 的合并器机制:每个节点返回的增量状态通过 reducer 合并到全局 state,而不是覆盖。

### 2.3 Runtime — Run / StreamBridge

#### `runtime/runs/schemas.py`

```python
class RunStatus(StrEnum):       # pending | running | success | error | timeout | interrupted
class DisconnectMode(StrEnum):  # cancel | continue_   SSE 客户端断开后是终止还是继续
```

#### `runtime/runs/manager.py` — `RunRecord` + `RunManager`

`RunRecord` 是**一次 Run 的可变运行时状态**:

- `run_id`(uuid)、`thread_id`、`assistant_id`
- `status: RunStatus`、`error: str | None`
- `on_disconnect: DisconnectMode`、`multitask_strategy: "reject" | "rollback" | "interrupt" | "enqueue"`
- `task: asyncio.Task` — 真正跑这次 run 的协程
- `abort_event: asyncio.Event`、`abort_action`(打断用)
- `metadata`、`kwargs`、`created_at / updated_at`(ISO)

`RunManager` 是**进程内 run 注册表**,asyncio.Lock 保护,提供 `create / get / list_by_thread / set_status` 等。它是「内存态」;**真正的会话状态由 LangGraph checkpointer 持久化**(SQLite / Postgres)。

#### `runtime/stream_bridge/base.py` — `StreamBridge`

解耦「Agent 工人(producer)」和「SSE 端点(consumer)」,仿 LangGraph Platform 的 Queue + StreamManager。

- `StreamEvent(id, event, data)`:一条 SSE 事件,`id` 单调递增以支持 `Last-Event-ID` 重连
- `HEARTBEAT_SENTINEL`、`END_SENTINEL`:特殊哨兵
- 实现:`memory.py`(进程内队列)、`async_provider.py`(可换 Redis)

### 2.4 Subagents — `subagents/`

**Subagent vs Lead Agent**:Lead 是用户直接对话的主控,通过 `task` 工具把子任务派给 subagent;subagent 用独立 system prompt + 受限工具集执行,结果作为 `ToolMessage` 返回主轴。

`SubagentConfig`:

| 字段 | 含义 |
|---|---|
| `name` | 标识 |
| `description` | 给 LLM 看,决定何时分派 |
| `system_prompt` | 子代理人格 |
| `tools / disallowed_tools` | 工具白/黑名单(默认禁 `task` 防嵌套) |
| `skills` | `None`=继承全部,`[]`=不加载,具体名=白名单 |
| `model` | 默认 `"inherit"` |
| `max_turns` | 默认 50 |
| `timeout_seconds` | 默认 900 |

注册顺序:**built-in(general-purpose、bash)→ config.yaml `custom_agents` → 每 agent 覆盖项**。

### 2.5 Sandbox — `sandbox/`

`Sandbox` 抽象基类定义 agent 可见的操作:`execute_command / read_file / write_file / list_dir / glob / grep`。

**主机路径**(`config/paths.py`):agent 看到的是真实的宿主机路径；`Paths` 类(`get_paths(thread_id)`)计算 `.deer-flow/<thread_id>/uploads/foo.pdf` 等实际路径，没有虚拟路径翻译。Skill 文件从 `skills.path` 下直接读取。

### 2.6 Skills — `skills/types.py`

`Skill` 是一份「可被 agent 加载的能力包」:

| 字段 | 含义 |
|---|---|
| `name / description / license` | 元数据 |
| `skill_dir / skill_file` | 宿主路径,后者是 `SKILL.md` |
| `relative_path / category` | 相对路径 + `public` 或 `custom` |
| `enabled` | 是否启用 |

> 代码中**没有** `SkillPack` 类型,字面意义的"技能包"就是 `Skill` + 它所在目录里的资源文件。

### 2.7 MCP — `config/extensions_config.py`

`McpServerConfig` 定义单个 MCP 服务器:

- `enabled`、`type: "stdio" | "sse" | "http"`
- stdio:`command / args / env`
- sse / http:`url / headers / oauth`
- `description`

`ExtensionsConfig` 聚合 `mcp_servers: dict[name → McpServerConfig]` 和 `skills: dict[name → {enabled}]`,从 `extensions_config.json` 读取(可被 `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 指定)。

### 2.8 Config — `config/app_config.py`

`AppConfig` 是**根配置**,从 `config.yaml` 加载:

| 字段 | 含义 |
|---|---|
| `models` | 可用 LLM 列表(`supports_thinking / supports_vision`) |
| `sandbox` | 沙箱后端 |
| `tools / tool_groups` | 工具注册表 |
| `skills / skill_evolution / extensions` | 技能与扩展 |
| `tool_search` | 工具延迟加载 |
| `title / summarization / memory` | 中间件功能配置 |
| `agents_api{enabled}` | 自定义 agent 管理 REST 是否暴露(默认关闭) |
| `subagents` | subagent 全局 / 自定义配置 |
| `guardrails` | 合规中间件 |
| `circuit_breaker` | LLM 熔断 |
| `token_usage{enabled}` | token 计数开关 |
| `checkpointer` | LangGraph checkpoint 后端(SQLite / Postgres) |
| `stream_bridge` | 流桥实现选择 |

`get_app_config()` 是单例访问点,`ContextVar` 让测试可临时覆盖,**mtime 变化时自动 reload**。

> 修改 schema 时记得在 `config.example.yaml` 里 bump `config_version`。

### 2.9 Tools — `tools/`

DeerFlow **没有自定义 `ToolSpec`**,工具就是 `langchain_core.tools.BaseTool`。注册侧用两个模型(`config/tool_config.py`):

```python
class ToolGroupConfig:    # name(group 名)
class ToolConfig:         # name, group, use="<dotted.path:variable>"
```

`use` 字段告诉 `deerflow.reflection.resolve_variable` 如何反射拿到 `BaseTool` 实例(例如 `deerflow.sandbox.tools:bash_tool`)。

`tools/__init__.py:get_available_tools(model_name, groups, subagent_enabled)` 在构建 lead agent 时按白名单 + 模型能力筛选返回工具列表。

**内置工具**(`tools/builtins/`):`task`(派发 subagent)、`clarification`、`view_image`、`present_file`、`tool_search`、`setup_agent`、`invoke_acp_agent`、`skill_manage`。

### 2.10 Gateway REST 模型 — `app/gateway/routers/`

这层 Pydantic 模型直接对应 LangGraph Platform 协议(前端 SDK 期望的 wire format)。

#### Thread(`threads.py`)

- `ThreadResponse{thread_id, status, created_at, updated_at, metadata, values, interrupts}`
  - `values` = 当前 channel 状态(用 `serialize_channel_values` 把 `BaseMessage` 转 dict)
- `ThreadCreateRequest{thread_id?, metadata}`、`ThreadSearchRequest{metadata, limit, offset, status}`
- `ThreadStateResponse{values, next, metadata, checkpoint, checkpoint_id, parent_checkpoint_id, created_at, tasks}` — 一次 checkpoint 的完整快照
- `ThreadStateUpdateRequest{values?, checkpoint_id?, checkpoint?, as_node?}` — 人工干预续跑
- `HistoryEntry / ThreadHistoryRequest` — 检查点历史回溯

#### Run(`thread_runs.py`)

`RunCreateRequest` 字段(LangGraph Platform 兼容):

| 字段 | 含义 |
|---|---|
| `assistant_id` | 用哪个 assistant |
| `input` | 输入(如 `{messages: [...]}`) |
| `command` | LangGraph 控制命令 |
| `metadata` | 自由元信息 |
| `config` | 覆盖 `RunnableConfig` |
| `context` | 覆盖 DeerFlow 自定义参数(`model_name / thinking_enabled / is_plan_mode / subagent_enabled / reasoning_effort` 等) |
| `webhook` | 完成回调 |
| `checkpoint_id / checkpoint` | 从某 checkpoint 续跑 |
| `interrupt_before / after` | 在指定节点前/后中断 |
| `stream_mode / stream_subgraphs / stream_resumable` | 流式控制 |
| `on_disconnect / on_completion` | 断连/完成行为 |
| `multitask_strategy` | 同 thread 多 run 冲突策略:`reject / rollback / interrupt / enqueue` |
| `after_seconds` | 延迟启动 |
| `if_not_exists` | thread 不存在时是否自动建 |
| `feedback_keys` | 反馈聚合键 |

`RunResponse` 是 `RunRecord` 的 JSON 投影。

---

## 3. Thread / Run / Assistant / Checkpoint 心智模型

LangGraph 协议的核心四件套:

| 概念 | 一句话定义 | 类比 | 在哪里 |
|---|---|---|---|
| **Assistant** | 一份「配置好的 agent」 = (graph + 默认 RunnableConfig + metadata) | AI 人格 / preset | `routers/assistants_compat.py`,默认 graph 名 `agent`(见 `langgraph.json`) |
| **Thread** | 一段持续对话,有 `thread_id`,持有自己的 checkpoint 历史和 `ThreadState` | 微信会话 | `threads.py` + checkpointer 表 |
| **Run** | 在某 thread 上的一次执行(一条用户消息 → 若干轮工具调用 → 回复结束) | "一回合" | `RunRecord` + `runs/worker.py` |
| **Checkpoint** | graph 状态在某时刻的序列化快照(channel values + next nodes + metadata),可从任一 checkpoint 分叉/续跑 | git commit | `CheckpointerConfig` 指定后端 |
| **Message** | thread 历史中的一条:`HumanMessage / AIMessage(可能含 tool_calls) / ToolMessage / SystemMessage` | 一条聊天气泡 | `langchain_core.messages` |

**典型生命周期**:

1. 前端选好 assistant
2. POST `/api/threads` 建 thread
3. POST `/api/threads/{tid}/runs/stream` 带 `input` 启动一次 run
4. 后端 `RunManager` 建 `RunRecord`
5. worker 跑 graph,每节点完成时由 checkpointer 落盘 + `StreamBridge` 推 SSE
6. 前端 `useStream` 实时拼装
7. 完成时 `RunStatus.success`

下次再来一句话,**新建一个 run,但 thread 同一个**,所以历史和工作区文件都还在。

---

## 4. 四个 RunnableConfig 标志

来自 `RunCreateRequest.context` 或 `config.configurable`,在 `make_lead_agent` 里读取:

| 标志 | 类型 | 作用 |
|---|---|---|
| `thinking_enabled` | `bool` | 是否开启模型 thinking / extended-reasoning。模型不支持时自动关掉 |
| `is_plan_mode` | `bool` | 启用 `TodoMiddleware`,绑定 `write_todos` + 任务追踪 prompt |
| `subagent_enabled` | `bool` | 启用 `task` 工具(派发 subagent)+ `SubagentLimitMiddleware` |
| `reasoning_effort` | `str?` | 透传给模型(OpenAI o-系列的 `low / medium / high`) |

**Flash / Reasoning / Pro / Ultra 四档**:

| 模式 | thinking_enabled | reasoning_effort | is_plan_mode | subagent_enabled | 行为 |
|---|---|---|---|---|---|
| Flash | false | — | false | false | 直接回答,最快 |
| Reasoning | true | low | false | false | CoT,无 plan |
| Pro | true | medium | true | false | + write_todos / TodoListMiddleware |
| Ultra | true | high | true | true | + task() / SubagentLimitMiddleware |

四档是嵌套递增(Ultra ⊃ Pro ⊃ Reasoning ⊃ Flash)。前端在 `frontend/src/core/threads/hooks.ts` 把模式映射到这 4 个 flag,模型 `supports_thinking=false` 时自动回落到 Flash。

**渠道侧覆盖**(`channels.session.context`):同样这 4 个 flag,在 yaml 里给 IM 用户(Feishu / Slack / Telegram / WeChat)预置;优先级 **user > channel > channels(全局) > backend defaults**。

---

## 5. 关键路径速查表

| 概念 | 文件 |
|---|---|
| 主代理工厂 | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` |
| 全局状态 schema | `backend/packages/harness/deerflow/agents/thread_state.py` |
| 中间件实现 | `backend/packages/harness/deerflow/agents/middlewares/` |
| 模型工厂 | `backend/packages/harness/deerflow/models/factory.py` |
| Run 注册表 | `backend/packages/harness/deerflow/runtime/runs/manager.py` |
| Run 状态枚举 | `backend/packages/harness/deerflow/runtime/runs/schemas.py` |
| Run worker | `backend/packages/harness/deerflow/runtime/runs/worker.py` |
| StreamBridge | `backend/packages/harness/deerflow/runtime/stream_bridge/` |
| Subagent 配置 | `backend/packages/harness/deerflow/subagents/config.py` |
| Subagent 注册 | `backend/packages/harness/deerflow/subagents/registry.py` |
| Subagent 执行 | `backend/packages/harness/deerflow/subagents/executor.py` |
| Sandbox 抽象 | `backend/packages/harness/deerflow/sandbox/sandbox.py` |
| 虚拟路径常量 | `backend/packages/harness/deerflow/config/paths.py` |
| Skill 实体 | `backend/packages/harness/deerflow/skills/types.py` |
| Skill 加载 | `backend/packages/harness/deerflow/skills/{loader,manager,parser,installer}.py` |
| MCP 服务器配置 | `backend/packages/harness/deerflow/config/extensions_config.py` |
| MCP 客户端构建 | `backend/packages/harness/deerflow/mcp/client.py` |
| 根配置 AppConfig | `backend/packages/harness/deerflow/config/app_config.py` |
| 工具注册声明 | `backend/packages/harness/deerflow/config/tool_config.py` |
| 工具收集 | `backend/packages/harness/deerflow/tools/__init__.py` |
| 内置工具 | `backend/packages/harness/deerflow/tools/builtins/` |
| Gateway 入口 | `backend/app/gateway/app.py` |
| Thread REST | `backend/app/gateway/routers/threads.py` |
| Run REST + SSE | `backend/app/gateway/routers/thread_runs.py` |
| LangGraph 注册 | `backend/langgraph.json` |

---

## 一句话总结

DeerFlow =
**「LangGraph 的 thread / run / checkpoint 协议」**
\+ **「自家的 Lead-Agent 中间件流水线」**
\+ **「Sandbox / Skill / MCP / Subagent 四件套扩展」**
\+ **「FastAPI Gateway 兼容 LangGraph Platform 协议暴露给前端」**

读懂下面四件事,你就理解了它的类型系统:

1. **`ThreadState`** 是一切流转的状态包(messages + sandbox + thread_data + artifacts + todos + viewed_images)。
2. **`RunnableConfig.configurable`** 里那 4 个 flag 决定 lead agent 这次长什么样。
3. **`RunRecord`**(内存)记一次执行,**`Checkpoint`**(落盘)记 graph 状态,**职责分离**。
4. **`AppConfig`** 是配置的根,所有子系统(模型、沙箱、技能、MCP、subagent、中间件)都从它派生开关。

---

## 参考阅读

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — 系统部署架构
- [`API.md`](API.md) — REST 接口完整参考
- [`STREAMING.md`](STREAMING.md) — SSE 流式细节
- [`middleware-execution-flow.md`](middleware-execution-flow.md) — 中间件执行顺序
- [`HARNESS_APP_SPLIT.md`](HARNESS_APP_SPLIT.md) — harness 与 app 边界
- [`CONFIGURATION.md`](CONFIGURATION.md) — 配置项详解
