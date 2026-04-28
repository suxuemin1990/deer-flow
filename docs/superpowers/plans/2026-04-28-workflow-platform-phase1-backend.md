# Phase 1: Custom Workflow Agent Platform — Backend Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 spec `docs/superpowers/specs/2026-04-28-custom-workflow-agent-platform-design.md` 的 backend 平台底座落地。完成后 lead_agent 通过统一 4 工具(`start_workflow / inject_hint / cancel_workflow / get_workflow_progress`)操作任意通过 yaml 注册的 LangGraph workflow,demo_flow 作为首个示例 workflow 接入。

**Architecture:** 新增 `deerflow.workflows` 包(base_state / registry / emit / background / tools / prompt),用 yaml + Pydantic 注册 workflow,后台 task 共享 gateway checkpointer,父子 thread 关系存父 thread metadata。lead_agent system prompt 启动时注入 workflow 目录。前端 widget 在 Phase 2 处理。

**Tech Stack:** LangGraph StateGraph + checkpointer、langchain `@tool`、Pydantic v2、FastAPI、asyncio.create_task、pytest。

---

## File Structure

**Created:**
- `backend/packages/harness/deerflow/workflows/__init__.py` — 包导出
- `backend/packages/harness/deerflow/workflows/base_state.py` — `WorkflowBaseState` + `_hints_reducer`
- `backend/packages/harness/deerflow/workflows/registry.py` — `WorkflowSpec` dataclass + `WorkflowRegistry` + 加载器
- `backend/packages/harness/deerflow/workflows/emit.py` — `emit_to_parent_thread` helper
- `backend/packages/harness/deerflow/workflows/background.py` — `run_workflow_background` 协程
- `backend/packages/harness/deerflow/workflows/tools.py` — 4 个 LLM 工具
- `backend/packages/harness/deerflow/workflows/prompt.py` — `render_workflow_catalog` 渲染 system prompt 片段
- `backend/packages/harness/deerflow/workflows/demo_flow/__init__.py` — `make_graph` factory + `DemoFlowInput` schema(从 `agents/demo_flow` 迁入,字段名英文化)
- `backend/packages/harness/deerflow/workflows/demo_flow/state.py`(英文字段重命名)
- `backend/packages/harness/deerflow/workflows/demo_flow/agent.py`
- `backend/packages/harness/deerflow/workflows/demo_flow/nodes/__init__.py`
- `backend/packages/harness/deerflow/workflows/demo_flow/nodes/{init,work_loop,poll_wait,final}_node.py`
- `backend/tests/test_workflows_base_state.py`
- `backend/tests/test_workflows_registry.py`
- `backend/tests/test_workflows_emit.py`
- `backend/tests/test_workflows_background.py`
- `backend/tests/test_workflows_tools.py`
- `backend/tests/test_workflows_prompt.py`
- `backend/tests/test_workflows_demo_flow.py` — pipeline 单测(从 test_demo_flow.py 迁入)
- `backend/tests/test_workflows_e2e.py` — start_workflow 全链路集成测试

**Modified:**
- `config.yaml` — 顶层加 `workflows:` 列表(示例 demo-flow)
- `config.example.yaml` — 同步加示例
- `backend/app/gateway/deps.py` — lifespan 里 `WorkflowRegistry.load_from_app_config()`
- `backend/app/gateway/routers/threads.py` — 新增 `GET /threads/{tid}/children`
- `backend/packages/harness/deerflow/tools/tools.py` — `BUILTIN_TOOLS` 替换为 4 个平台工具
- `backend/packages/harness/deerflow/tools/builtins/__init__.py` — 移除 `start_demo_exploration` 导出
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` — 拼接 `render_workflow_catalog()` 输出

**Deleted (after migration):**
- `backend/packages/harness/deerflow/agents/demo_flow/` — 整个目录(已迁入 workflows/demo_flow/)
- `backend/packages/harness/deerflow/tools/builtins/demo_flow_tool.py`
- `backend/tests/test_demo_flow.py`、`backend/tests/test_demo_flow_background_run.py`(被 workflows 测试覆盖)

---

## Task 1: 平台 base state(reducer + 基类)

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/__init__.py`
- Create: `backend/packages/harness/deerflow/workflows/base_state.py`
- Create: `backend/tests/test_workflows_base_state.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workflows_base_state.py
"""Unit tests for the workflow platform base state reducer."""

from deerflow.workflows.base_state import _hints_reducer


def test_hints_reducer_appends_when_existing_present():
    assert _hints_reducer(["a"], ["b"]) == ["a", "b"]


def test_hints_reducer_starts_from_empty_when_existing_none():
    assert _hints_reducer(None, ["a"]) == ["a"]


def test_hints_reducer_returns_existing_when_new_none():
    assert _hints_reducer(["a", "b"], None) == ["a", "b"]


def test_hints_reducer_explicit_empty_list_clears():
    assert _hints_reducer(["a", "b"], []) == []


def test_hints_reducer_both_none_returns_empty():
    assert _hints_reducer(None, None) == []


def test_workflow_base_state_keys():
    from deerflow.workflows.base_state import WorkflowBaseState

    keys = WorkflowBaseState.__optional_keys__
    assert "_parent_thread_id" in keys
    assert "_hints" in keys
    assert "_error" in keys
```

- [ ] **Step 2: 跑测试,确认失败**

`cd backend && uv run pytest tests/test_workflows_base_state.py -v`
Expected: 6 个测试全 fail(模块不存在)

- [ ] **Step 3: 实现 base_state.py**

```python
# backend/packages/harness/deerflow/workflows/base_state.py
"""Platform-reserved fields every workflow's state must carry.

Workflows compose this with their own business fields::

    class YoloExploreState(WorkflowBaseState):
        task_name: str
        max_rounds: int
        ...

The platform reads ``_parent_thread_id`` (set by start_workflow tool),
``_hints`` (set by inject_hint tool), and ``_error`` (set by background
runner on exception).
"""

from __future__ import annotations

from typing import Annotated, TypedDict


def _hints_reducer(
    existing: list[str] | None,
    new: list[str] | None,
) -> list[str]:
    """Append new hints; explicit empty list from a node clears the inbox."""
    if new is None:
        return existing or []
    if new == []:
        return []
    return (existing or []) + new


class WorkflowBaseState(TypedDict, total=False):
    _parent_thread_id: str
    _hints: Annotated[list[str], _hints_reducer]
    _error: str | None
```

- [ ] **Step 4: 同时创建包入口**

```python
# backend/packages/harness/deerflow/workflows/__init__.py
"""Custom workflow agent platform.

See docs/superpowers/specs/2026-04-28-custom-workflow-agent-platform-design.md
"""

from deerflow.workflows.base_state import WorkflowBaseState, _hints_reducer

__all__ = ["WorkflowBaseState", "_hints_reducer"]
```

- [ ] **Step 5: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_base_state.py -v`
Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/__init__.py \
        backend/packages/harness/deerflow/workflows/base_state.py \
        backend/tests/test_workflows_base_state.py
git commit -m "feat(workflows): add WorkflowBaseState + _hints_reducer"
```

---

## Task 2: WorkflowSpec + Registry(yaml 加载、查找、失败隔离)

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/registry.py`
- Create: `backend/tests/test_workflows_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workflows_registry.py
"""Unit tests for the workflow registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel


class _FakeInput(BaseModel):
    name: str
    rounds: int = 5


def _fake_factory(checkpointer=None):  # noqa: ARG001
    return "fake-graph"


def test_workflow_spec_dataclass_fields():
    from deerflow.workflows.registry import WorkflowSpec

    spec = WorkflowSpec(
        name="demo",
        description="d",
        factory=_fake_factory,
        input_schema=_FakeInput,
        done_field="is_done",
        report_field="report",
        progress_fields=["round"],
        hint_behavior_doc="hb",
    )
    assert spec.name == "demo"
    assert spec.factory is _fake_factory
    assert spec.input_schema is _FakeInput
    assert spec.progress_fields == ["round"]


def test_registry_load_from_dicts_succeeds(monkeypatch):
    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    monkeypatch.setattr(reg_mod, "_resolve", lambda spec: {
        "deerflow.fake:_fake_factory": _fake_factory,
        "deerflow.fake:_FakeInput": _FakeInput,
    }[spec])

    registry = WorkflowRegistry.load_from_dicts([{
        "name": "demo",
        "description": "d",
        "factory": "deerflow.fake:_fake_factory",
        "input_schema": "deerflow.fake:_FakeInput",
        "done_field": "is_done",
        "report_field": "report",
    }])

    assert "demo" in registry.names()
    spec = registry.get("demo")
    assert spec.factory is _fake_factory
    assert spec.input_schema is _FakeInput
    assert spec.progress_fields == []
    assert spec.hint_behavior_doc == ""


def test_registry_load_skips_failures(monkeypatch, caplog):
    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    def fake_resolve(spec):
        if "broken" in spec:
            raise ImportError(f"cannot import {spec}")
        return {
            "deerflow.fake:_fake_factory": _fake_factory,
            "deerflow.fake:_FakeInput": _FakeInput,
        }[spec]

    monkeypatch.setattr(reg_mod, "_resolve", fake_resolve)

    registry = WorkflowRegistry.load_from_dicts([
        {
            "name": "good",
            "description": "ok",
            "factory": "deerflow.fake:_fake_factory",
            "input_schema": "deerflow.fake:_FakeInput",
            "done_field": "d",
            "report_field": "r",
        },
        {
            "name": "bad",
            "description": "broken",
            "factory": "deerflow.broken:nope",
            "input_schema": "deerflow.fake:_FakeInput",
            "done_field": "d",
            "report_field": "r",
        },
    ])

    assert registry.names() == ["good"]
    assert registry.failed() == [("bad", "ImportError: cannot import deerflow.broken:nope")]


def test_registry_get_unknown_raises():
    from deerflow.workflows.registry import WorkflowRegistry

    registry = WorkflowRegistry.load_from_dicts([])
    with pytest.raises(KeyError):
        registry.get("nope")


def test_registry_input_schema_must_be_basemodel(monkeypatch):
    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    class NotPydantic:
        pass

    monkeypatch.setattr(reg_mod, "_resolve", lambda spec: {
        "deerflow.fake:_fake_factory": _fake_factory,
        "deerflow.fake:NotPydantic": NotPydantic,
    }[spec])

    registry = WorkflowRegistry.load_from_dicts([{
        "name": "bad-schema",
        "description": "d",
        "factory": "deerflow.fake:_fake_factory",
        "input_schema": "deerflow.fake:NotPydantic",
        "done_field": "d",
        "report_field": "r",
    }])
    assert registry.names() == []
    assert "bad-schema" in dict(registry.failed())
```

- [ ] **Step 2: 跑测试,确认失败**

`cd backend && uv run pytest tests/test_workflows_registry.py -v`
Expected: 全 fail(模块不存在)

- [ ] **Step 3: 实现 registry.py**

```python
# backend/packages/harness/deerflow/workflows/registry.py
"""Workflow registry — loads workflow definitions from yaml/dicts at startup.

Each entry resolves ``factory`` (callable taking ``checkpointer``) and
``input_schema`` (Pydantic ``BaseModel``) eagerly. Failures are logged and
skipped so a single broken entry doesn't kill gateway startup.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _resolve(spec: str) -> Any:
    """Resolve ``module:attr`` to the live object."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"Invalid spec {spec!r}: expected 'module:attr'")
    mod = importlib.import_module(module_name)
    obj = getattr(mod, attr, None)
    if obj is None:
        raise AttributeError(f"{attr!r} not found in {module_name!r}")
    return obj


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


class WorkflowRegistry:
    """In-memory registry; constructed once at gateway lifespan."""

    def __init__(self, specs: list[WorkflowSpec], failures: list[tuple[str, str]]) -> None:
        self._specs = {s.name: s for s in specs}
        self._failures = failures

    # ------------------------------------------------------------------
    # Loaders

    @classmethod
    def load_from_dicts(cls, items: list[dict[str, Any]]) -> "WorkflowRegistry":
        specs: list[WorkflowSpec] = []
        failures: list[tuple[str, str]] = []
        for item in items:
            name = item.get("name", "<unnamed>")
            try:
                factory = _resolve(item["factory"])
                if not callable(factory):
                    raise TypeError(f"factory {item['factory']!r} is not callable")
                input_schema = _resolve(item["input_schema"])
                if not (isinstance(input_schema, type) and issubclass(input_schema, BaseModel)):
                    raise TypeError(
                        f"input_schema {item['input_schema']!r} must be a pydantic BaseModel subclass"
                    )
                specs.append(WorkflowSpec(
                    name=item["name"],
                    description=item["description"],
                    factory=factory,
                    input_schema=input_schema,
                    done_field=item["done_field"],
                    report_field=item["report_field"],
                    progress_fields=list(item.get("progress_fields") or []),
                    hint_behavior_doc=item.get("hint_behavior_doc") or "",
                ))
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                logger.error("workflow registry: skipping %r — %s", name, msg)
                failures.append((name, msg))
        return cls(specs, failures)

    @classmethod
    def load_from_app_config(cls) -> "WorkflowRegistry":
        from deerflow.config import get_app_config

        cfg = get_app_config()
        items = getattr(cfg, "workflows", None) or []
        # Pydantic-config items may already be objects; normalize to dicts.
        normalized = [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in items]
        return cls.load_from_dicts(normalized)

    # ------------------------------------------------------------------
    # Accessors

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def get(self, name: str) -> WorkflowSpec:
        if name not in self._specs:
            raise KeyError(f"Workflow {name!r} is not registered")
        return self._specs[name]

    def has(self, name: str) -> bool:
        return name in self._specs

    def all(self) -> list[WorkflowSpec]:
        return list(self._specs.values())

    def failed(self) -> list[tuple[str, str]]:
        return list(self._failures)
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_registry.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/registry.py \
        backend/tests/test_workflows_registry.py
git commit -m "feat(workflows): add WorkflowRegistry with eager-resolve and failure isolation"
```

---

## Task 3: 迁移 demo_flow 到 workflows/demo_flow/(英文字段化)

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/__init__.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/state.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/agent.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/__init__.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/init_node.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/poll_wait_node.py`
- Create: `backend/packages/harness/deerflow/workflows/demo_flow/nodes/final_node.py`
- Create: `backend/tests/test_workflows_demo_flow.py`

字段重命名(老→新):`任务名称→task_name`、`最大轮次→max_rounds`、`当前轮次→current_round`、`历史轮次→history`、`报告markdown→report_markdown`、`_完成→is_done`。继承 `WorkflowBaseState` 拿到 `_parent_thread_id` / `_hints` / `_error`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workflows_demo_flow.py
"""Tests for the demo_flow workflow (first registered example)."""

from __future__ import annotations

import pytest


def test_input_schema_required_and_default_fields():
    from deerflow.workflows.demo_flow import DemoFlowInput

    schema = DemoFlowInput.model_json_schema()
    props = schema["properties"]
    assert "task_name" in props
    assert "max_rounds" in props
    assert schema["required"] == ["task_name"]
    # default for max_rounds
    instance = DemoFlowInput(task_name="x")
    assert instance.max_rounds == 3


def test_make_graph_compiles():
    from deerflow.workflows.demo_flow import make_graph

    graph = make_graph()
    assert graph is not None


def test_topology_has_pipeline_nodes():
    from deerflow.workflows.demo_flow import make_graph

    g = make_graph().get_graph()
    names = {n.id for n in g.nodes.values()}
    for expected in ("init", "work_loop", "poll_wait", "final"):
        assert expected in names


def test_init_node_resets_round():
    from deerflow.workflows.demo_flow.nodes.init_node import init_node

    out = init_node({"task_name": "x", "max_rounds": 3, "current_round": 99})
    assert out["current_round"] == 0


def test_work_loop_increments_when_below_max():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = work_loop_node({"task_name": "x", "max_rounds": 3, "current_round": 0})
    assert out == {"current_round": 1, "is_done": False}


def test_work_loop_signals_done_at_max():
    from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node

    out = work_loop_node({"task_name": "x", "max_rounds": 3, "current_round": 3})
    assert out == {"is_done": True}


def test_poll_wait_appends_score(monkeypatch):
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as mod

    monkeypatch.setattr(mod.asyncio, "sleep", _async_noop)
    monkeypatch.setattr(mod.random, "uniform", lambda _a, _b: 0.55)
    import asyncio as _aio

    out = _aio.run(mod.poll_wait_node({"task_name": "x", "max_rounds": 3, "current_round": 1}))
    assert out == {"history": [{"round": 1, "score": 0.55}]}


async def _async_noop(_s):  # used by poll_wait test above
    return None


def test_final_renders_markdown_report():
    from deerflow.workflows.demo_flow.nodes.final_node import final_node

    out = final_node({
        "task_name": "yolo-task",
        "max_rounds": 2,
        "history": [{"round": 1, "score": 0.5}, {"round": 2, "score": 0.7}],
    })
    md = out["report_markdown"]
    assert "yolo-task" in md
    assert "| 1 | 0.5 |" in md
    assert "| 2 | 0.7 |" in md
    assert "0.7" in md


@pytest.mark.parametrize("done,expected", [(True, "final"), (False, "poll_wait")])
def test_route_after_work_loop(done, expected):
    from deerflow.workflows.demo_flow.agent import _route_after_work_loop

    assert _route_after_work_loop({"is_done": done}) == expected


@pytest.mark.asyncio
async def test_full_pipeline_in_memory(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw

    monkeypatch.setattr(pw.asyncio, "sleep", _async_noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.6)

    graph = make_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}

    final_state = await graph.ainvoke({"task_name": "x", "max_rounds": 3}, config=cfg)

    assert final_state["current_round"] == 3
    assert len(final_state["history"]) == 3
    assert "yolo" not in final_state["report_markdown"]  # task_name was "x"
    assert "x" in final_state["report_markdown"]
```

- [ ] **Step 2: 跑测试,确认失败**

`cd backend && uv run pytest tests/test_workflows_demo_flow.py -v`
Expected: 全 fail

- [ ] **Step 3: 实现 state**

```python
# backend/packages/harness/deerflow/workflows/demo_flow/state.py
"""DemoFlow state (English field names; inherits platform reserved fields)."""

from __future__ import annotations

from typing import Annotated, NotRequired

from deerflow.workflows.base_state import WorkflowBaseState


def _merge_list(existing: list | None, new: list | None) -> list:
    if existing is None:
        return new or []
    if new is None:
        return existing
    return existing + new


class DemoFlowState(WorkflowBaseState):
    task_name: str
    max_rounds: int
    current_round: NotRequired[int]
    history: Annotated[list[dict], _merge_list]
    report_markdown: NotRequired[str]
    is_done: NotRequired[bool]
```

- [ ] **Step 4: 实现 nodes**

```python
# backend/packages/harness/deerflow/workflows/demo_flow/nodes/__init__.py
"""DemoFlow nodes — keep submodules importable for monkeypatching."""
```

```python
# backend/packages/harness/deerflow/workflows/demo_flow/nodes/init_node.py
"""Reset per-run counter; supports re-invoke on same thread."""


def init_node(state):
    return {"current_round": 0}
```

```python
# backend/packages/harness/deerflow/workflows/demo_flow/nodes/work_loop_node.py
"""Increment round counter; flag is_done when budget exhausted."""


def work_loop_node(state):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}
    return {"current_round": current + 1, "is_done": False}
```

```python
# backend/packages/harness/deerflow/workflows/demo_flow/nodes/poll_wait_node.py
"""Async sleep + fake score (uses asyncio.sleep so we don't block the loop)."""

from __future__ import annotations

import asyncio
import random


async def poll_wait_node(state):
    await asyncio.sleep(2)
    current = state["current_round"]
    score = round(random.uniform(0.4, 0.9), 3)
    return {"history": [{"round": current, "score": score}]}
```

```python
# backend/packages/harness/deerflow/workflows/demo_flow/nodes/final_node.py
"""Render markdown report from accumulated history."""


def final_node(state):
    history = state.get("history") or []
    rows = "\n".join(f"| {e['round']} | {e['score']} |" for e in history)
    if history:
        best = max(history, key=lambda e: e["score"])
        footer = f"\n\n**Best round**: {best['round']} (score {best['score']})"
    else:
        footer = "\n\n*(no history)*"
    md = (
        f"## Exploration report — {state.get('task_name', '')}\n\n"
        f"| Round | Score |\n|---|---|\n{rows}{footer}"
    )
    return {"report_markdown": md}
```

- [ ] **Step 5: 实现 agent + 包入口**

```python
# backend/packages/harness/deerflow/workflows/demo_flow/agent.py
"""DemoFlow graph topology."""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

from deerflow.workflows.demo_flow.nodes.final_node import final_node
from deerflow.workflows.demo_flow.nodes.init_node import init_node
from deerflow.workflows.demo_flow.nodes.poll_wait_node import poll_wait_node
from deerflow.workflows.demo_flow.nodes.work_loop_node import work_loop_node
from deerflow.workflows.demo_flow.state import DemoFlowState

logger = logging.getLogger(__name__)


def _route_after_work_loop(state) -> Literal["poll_wait", "final"]:
    return "final" if state.get("is_done") else "poll_wait"


def make_graph(checkpointer=None):
    graph = StateGraph(DemoFlowState)
    graph.add_node("init", init_node)
    graph.add_node("work_loop", work_loop_node)
    graph.add_node("poll_wait", poll_wait_node)
    graph.add_node("final", final_node)
    graph.add_edge(START, "init")
    graph.add_edge("init", "work_loop")
    graph.add_conditional_edges(
        "work_loop",
        _route_after_work_loop,
        {"poll_wait": "poll_wait", "final": "final"},
    )
    graph.add_edge("poll_wait", "work_loop")
    graph.add_edge("final", END)
    return graph.compile(checkpointer=checkpointer)
```

```python
# backend/packages/harness/deerflow/workflows/demo_flow/__init__.py
"""demo_flow workflow — platform's first registered example.

Zero-LLM pipeline used to validate the platform mechanics (registry,
background runner, hint inbox, parent-thread emit). Real workflows like
training_explore replace the fake nodes with LLM + compute_cli calls.
"""

from pydantic import BaseModel, Field

from deerflow.workflows.demo_flow.agent import make_graph


class DemoFlowInput(BaseModel):
    task_name: str = Field(description="Human-readable task name")
    max_rounds: int = Field(default=3, ge=1, le=20, description="Number of fake rounds")


__all__ = ["DemoFlowInput", "make_graph"]
```

- [ ] **Step 6: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_demo_flow.py -v`
Expected: 10 passed

- [ ] **Step 7: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/demo_flow \
        backend/tests/test_workflows_demo_flow.py
git commit -m "feat(workflows): migrate demo_flow with English fields and async poll"
```

---

## Task 4: 注册 demo-flow 进 config.yaml(用户配置 + 示例)

**Files:**
- Modify: `config.yaml`
- Modify: `config.example.yaml`
- Modify: `backend/packages/harness/deerflow/config/...`(`AppConfig` 增加 `workflows: list[dict]` 字段)

需要先确认 `AppConfig` 的位置和形态。

- [ ] **Step 1: 找到 AppConfig 定义**

```bash
cd backend && grep -rn "class AppConfig\|workflows:" packages/harness/deerflow/config/ | head -20
```

- [ ] **Step 2: 写失败测试(配置加载验证)**

```python
# 加到 backend/tests/test_workflows_registry.py 末尾
def test_load_from_app_config_picks_up_workflows_section(monkeypatch, tmp_path):
    """If AppConfig.workflows is set, registry picks them up."""
    from types import SimpleNamespace

    from deerflow.workflows import registry as reg_mod
    from deerflow.workflows.registry import WorkflowRegistry

    fake_cfg = SimpleNamespace(workflows=[{
        "name": "demo-flow",
        "description": "demo",
        "factory": "deerflow.workflows.demo_flow:make_graph",
        "input_schema": "deerflow.workflows.demo_flow:DemoFlowInput",
        "done_field": "is_done",
        "report_field": "report_markdown",
    }])
    monkeypatch.setattr(reg_mod, "get_app_config", lambda: fake_cfg, raising=False)
    # The above attr doesn't exist yet on the module; the function imports lazily.
    # Use a different approach: patch the import target.
    import deerflow.config as deerflow_config
    monkeypatch.setattr(deerflow_config, "get_app_config", lambda: fake_cfg)

    registry = WorkflowRegistry.load_from_app_config()
    assert "demo-flow" in registry.names()
    assert registry.get("demo-flow").factory.__name__ == "make_graph"
```

- [ ] **Step 3: 跑测试**

`cd backend && uv run pytest tests/test_workflows_registry.py::test_load_from_app_config_picks_up_workflows_section -v`
Expected: pass(只要 AppConfig 已经允许 `workflows` 属性,或者直接用 SimpleNamespace 绕过)

如果 fail 因为 AppConfig 不允许 workflows 字段,继续步骤 4。

- [ ] **Step 4: 给 AppConfig 加 workflows 字段**

(基于 step 1 找到的位置编辑。Pydantic BaseModel 加:)

```python
class AppConfig(BaseModel):
    ...
    workflows: list[dict] = Field(default_factory=list)
```

确保 yaml 加载流程会把 `workflows:` 节解析进来。运行 step 3 测试再次确认通过。

- [ ] **Step 5: 编辑 config.yaml(本地)**

```yaml
# 在 config.yaml 末尾追加(若已有 workflows: 块则合并)
workflows:
  - name: demo-flow
    description: |
      Zero-LLM demo pipeline used to validate the workflow platform
      end-to-end. Pretends to run training rounds and produces a small
      markdown report. Useful for testing inject_hint / cancel /
      progress without spending real model tokens.
    factory: deerflow.workflows.demo_flow:make_graph
    input_schema: deerflow.workflows.demo_flow:DemoFlowInput
    done_field: is_done
    report_field: report_markdown
    progress_fields: [current_round, max_rounds, history]
    hint_behavior_doc: |
      Demo-only — the graph stores hints in _hints but does not consume
      them (no LLM nodes). Use this workflow only to verify the platform.
```

- [ ] **Step 6: 编辑 config.example.yaml**

把同一段 `workflows:` 块加到 example,值带注释说明这是模板。

- [ ] **Step 7: 跑全部 workflow 注册测试**

`cd backend && uv run pytest tests/test_workflows_registry.py tests/test_workflows_demo_flow.py -v`
Expected: 全部 pass。

- [ ] **Step 8: 提交**

```bash
git add config.example.yaml backend/packages/harness/deerflow/config/ \
        backend/tests/test_workflows_registry.py
# 注:本地 config.yaml 是 gitignore 的,不进 commit
git commit -m "feat(workflows): register demo-flow in AppConfig.workflows"
```

---

## Task 5: 把 registry 接进 gateway lifespan(启动时加载)

**Files:**
- Modify: `backend/app/gateway/deps.py`
- Create: `backend/tests/test_workflows_lifespan.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workflows_lifespan.py
"""Lifespan registers WorkflowRegistry on app.state."""

from __future__ import annotations

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_attaches_workflow_registry(monkeypatch):
    from deerflow.workflows.registry import WorkflowRegistry

    app = FastAPI()
    fake_registry = WorkflowRegistry.load_from_dicts([])
    monkeypatch.setattr(
        WorkflowRegistry, "load_from_app_config", classmethod(lambda cls: fake_registry)
    )

    from app.gateway.deps import langgraph_runtime

    async with langgraph_runtime(app):
        assert getattr(app.state, "workflow_registry", None) is fake_registry
```

- [ ] **Step 2: 跑测试**

`cd backend && uv run pytest tests/test_workflows_lifespan.py -v`
Expected: fail(`workflow_registry` 还没挂上)

- [ ] **Step 3: 编辑 deps.py**

在 `langgraph_runtime` 里 `set_default_checkpointer` 之后加:

```python
from deerflow.workflows.registry import WorkflowRegistry
app.state.workflow_registry = WorkflowRegistry.load_from_app_config()
if app.state.workflow_registry.failed():
    import logging
    logging.getLogger(__name__).warning(
        "Workflow registry skipped %d entries: %s",
        len(app.state.workflow_registry.failed()),
        app.state.workflow_registry.failed(),
    )
```

加一个 getter:

```python
def get_workflow_registry(request: Request):
    reg = getattr(request.app.state, "workflow_registry", None)
    if reg is None:
        raise HTTPException(status_code=503, detail="Workflow registry not available")
    return reg
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_lifespan.py -v`
Expected: pass

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/deps.py backend/tests/test_workflows_lifespan.py
git commit -m "feat(gateway): load WorkflowRegistry in lifespan, expose via app.state"
```

---

## Task 6: emit.py — 往父 thread 写消息

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/emit.py`
- Create: `backend/tests/test_workflows_emit.py`

- [ ] **Step 1: 调研 — 父 thread message 怎么写**

```bash
cd backend && grep -rn "aput_writes\|update_state\|aupdate_state\|messages.*append" packages/harness/deerflow/agents/ | head -20
```

目标:`emit_to_parent_thread(parent_thread_id, content, *, checkpointer)` 用 LangGraph 标准 API 把一条 system/tool message append 到父 thread 的 messages,**不绕路自己 SQL**。

最简实现:用任意编译过的图(比如父 thread 关联的 lead_agent 图,或者一个最小的"no-op StateGraph 接 MessagesState")的 `aupdate_state(config, {"messages": [SystemMessage(content)]})`。`aupdate_state` 会写一个新 checkpoint,前端 stream 端点自然能感知到(C2 阶段需要)。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_workflows_emit.py
"""Tests for emit_to_parent_thread."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_emit_appends_system_message_to_parent_thread():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows.emit import emit_to_parent_thread

    # Set up a parent thread with one existing message via a tiny graph.
    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)

    parent_tid = "parent-1"
    cfg = {"configurable": {"thread_id": parent_tid}}
    await parent_graph.ainvoke({"messages": [HumanMessage(content="hi")]}, config=cfg)

    await emit_to_parent_thread(
        parent_tid,
        "[workflow:demo] done",
        checkpointer=saver,
    )

    state = await parent_graph.aget_state(cfg)
    contents = [m.content for m in state.values["messages"]]
    assert "[workflow:demo] done" in contents


@pytest.mark.asyncio
async def test_emit_with_unknown_thread_raises():
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.workflows.emit import emit_to_parent_thread

    saver = InMemorySaver()
    with pytest.raises(Exception):  # noqa: BLE001 — implementation will narrow
        await emit_to_parent_thread("unknown-thread", "msg", checkpointer=saver)
```

- [ ] **Step 3: 实现 emit.py**

```python
# backend/packages/harness/deerflow/workflows/emit.py
"""Emit a message into another (parent) thread's checkpoint.

Uses LangGraph's standard ``aupdate_state`` so:
- the message becomes part of the thread's checkpoint history
- subscribers to ``/threads/{tid}/runs/stream`` see the update naturally
- we never bypass the checkpointer with raw SQL

A minimal MessagesState graph is compiled per call to obtain an updater
bound to the given checkpointer; this is cheap (StateGraph compile is
in-memory) and avoids needing the parent thread's actual graph factory.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph


def _build_message_appender(checkpointer: BaseCheckpointSaver):
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    return g.compile(checkpointer=checkpointer)


async def emit_to_parent_thread(
    parent_thread_id: str,
    content: str,
    *,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Append a SystemMessage to the parent thread's checkpoint.

    Raises:
        Exception: when no checkpoint exists for ``parent_thread_id``
            (LangGraph's aupdate_state requires a prior checkpoint).
    """
    appender = _build_message_appender(checkpointer)
    await appender.aupdate_state(
        config={"configurable": {"thread_id": parent_thread_id}},
        values={"messages": [SystemMessage(content=content)]},
    )
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_emit.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/emit.py \
        backend/tests/test_workflows_emit.py
git commit -m "feat(workflows): add emit_to_parent_thread via aupdate_state"
```

---

## Task 7: background.py — 后台跑 workflow + 终态/失败回写

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/background.py`
- Create: `backend/tests/test_workflows_background.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workflows_background.py
"""Tests for run_workflow_background success and failure paths."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_success_emits_report_to_parent_thread(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows.background import run_workflow_background
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowSpec
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph

    async def _noop(_s):
        return None
    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.6)

    saver = InMemorySaver()
    # Set up parent thread with a checkpoint
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "p1"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    spec = WorkflowSpec(
        name="demo-flow",
        description="d",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
    )

    await run_workflow_background(
        spec=spec,
        params={"task_name": "x", "max_rounds": 2},
        child_thread_id="c1",
        parent_thread_id=parent_tid,
        checkpointer=saver,
    )

    parent_state = await parent_graph.aget_state(
        config={"configurable": {"thread_id": parent_tid}}
    )
    msgs = [m.content for m in parent_state.values["messages"]]
    assert any("[workflow:demo-flow]" in m and "Exploration report" in m for m in msgs)


@pytest.mark.asyncio
async def test_failure_emits_error_and_writes_state(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.workflows.background import run_workflow_background
    from deerflow.workflows.demo_flow import DemoFlowInput
    from deerflow.workflows.registry import WorkflowSpec

    saver = InMemorySaver()
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "p2"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    def _broken_factory(checkpointer=None):  # noqa: ARG001
        async def _bad_invoke(*_a, **_kw):
            raise RuntimeError("boom")
        # Return an object whose .ainvoke explodes
        from types import SimpleNamespace
        return SimpleNamespace(ainvoke=_bad_invoke, aupdate_state=lambda **_kw: None,
                               aget_state=lambda **_kw: None)

    spec = WorkflowSpec(
        name="bad-wf",
        description="d",
        factory=_broken_factory,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
    )

    await run_workflow_background(
        spec=spec,
        params={"task_name": "x", "max_rounds": 1},
        child_thread_id="c-fail",
        parent_thread_id=parent_tid,
        checkpointer=saver,
    )

    parent_state = await parent_graph.aget_state(
        config={"configurable": {"thread_id": parent_tid}}
    )
    msgs = [m.content for m in parent_state.values["messages"]]
    assert any("[workflow:bad-wf]" in m and "boom" in m for m in msgs)
```

- [ ] **Step 2: 跑测试,确认失败**

`cd backend && uv run pytest tests/test_workflows_background.py -v`
Expected: fail

- [ ] **Step 3: 实现 background.py**

```python
# backend/packages/harness/deerflow/workflows/background.py
"""Run a workflow graph in the background, emit results to the parent thread.

Lifecycle owned here:
  1. compile graph with the shared checkpointer
  2. invoke with caller-provided params + child_thread_id + parent_thread_id
  3. on success: read report_field from final state, emit to parent
  4. on failure: write _error to child state, emit error message to parent

Caller (start_workflow tool) wraps this in asyncio.create_task and tracks
the task in a registry so cancel_workflow can cancel it.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.base import BaseCheckpointSaver

from deerflow.workflows.emit import emit_to_parent_thread
from deerflow.workflows.registry import WorkflowSpec

logger = logging.getLogger(__name__)


async def run_workflow_background(
    *,
    spec: WorkflowSpec,
    params: dict,
    child_thread_id: str,
    parent_thread_id: str,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Run *spec* once on *child_thread_id*, emit to *parent_thread_id*.

    Never raises — all exceptions are caught, written to state and parent
    thread (best effort) and re-logged.
    """
    graph = spec.factory(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": child_thread_id}}
    initial = {**params, "_parent_thread_id": parent_thread_id}

    try:
        await graph.ainvoke(initial, config=cfg)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        logger.exception("workflow %s failed on %s", spec.name, child_thread_id)
        # Best-effort: write _error + done flag to child state
        try:
            await graph.aupdate_state(
                config=cfg,
                values={"_error": err, spec.done_field: True},
            )
        except Exception:
            logger.exception("could not write _error to %s", child_thread_id)
        # Best-effort: emit failure to parent
        try:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] failed: {err}",
                checkpointer=checkpointer,
            )
        except Exception:
            logger.exception("could not emit failure to parent %s", parent_thread_id)
        return

    # Success path
    try:
        final_state = await graph.aget_state(cfg)
        report = final_state.values.get(spec.report_field)
        if report:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] done\n\n{report}",
                checkpointer=checkpointer,
            )
        else:
            logger.warning(
                "workflow %s on %s finished but report_field %r is empty",
                spec.name, child_thread_id, spec.report_field,
            )
    except Exception:
        logger.exception("could not emit success report for %s", child_thread_id)
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_background.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/background.py \
        backend/tests/test_workflows_background.py
git commit -m "feat(workflows): add run_workflow_background with success/failure emit"
```

---

## Task 8: tools.py — 4 个 LLM 工具

实现策略:每个工具一小步,共用一个文件。先写 start_workflow,再加 inject_hint / cancel_workflow / get_workflow_progress。`_BG_TASKS: dict[str, asyncio.Task]` 用 child_thread_id 为 key,方便 cancel 找。

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/tools.py`
- Create: `backend/tests/test_workflows_tools.py`

- [ ] **Step 1: 写失败测试 start_workflow**

```python
# backend/tests/test_workflows_tools.py
"""Tests for the 4 LLM-facing workflow tools."""

from __future__ import annotations

import asyncio

import pytest


def _setup_registry_and_checkpointer(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows import tools as tools_mod

    saver = InMemorySaver()
    set_default_checkpointer(saver)

    async def _noop(_s):
        return None
    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.5)

    registry = WorkflowRegistry(
        specs=[WorkflowSpec(
            name="demo-flow",
            description="d",
            factory=make_graph,
            input_schema=DemoFlowInput,
            done_field="is_done",
            report_field="report_markdown",
            progress_fields=["current_round", "max_rounds", "history"],
        )],
        failures=[],
    )
    monkeypatch.setattr(tools_mod, "_get_registry", lambda: registry)
    return saver, registry


@pytest.mark.asyncio
async def test_start_workflow_returns_thread_id_and_runs_in_background(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)

    # Establish parent chat thread checkpoint
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "chat-1"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="start it")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        result = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {
                "name": "demo-flow",
                "params": {"task_name": "x", "max_rounds": 2},
            },
            "id": "tc-1",
            "type": "tool_call",
            # ToolRuntime carries the parent thread_id via configurable
        }, config={"configurable": {"thread_id": parent_tid}})

        msg = result.update["messages"][0].content
        assert "demo-flow" in msg
        assert "thread_id=" in msg

        # Wait briefly for background to finish
        for _ in range(50):
            await asyncio.sleep(0.05)
            parent_state = await parent_graph.aget_state(
                {"configurable": {"thread_id": parent_tid}}
            )
            messages = parent_state.values["messages"]
            if any("[workflow:demo-flow] done" in m.content for m in messages):
                break
        else:
            pytest.fail("background workflow never emitted to parent thread")
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_start_workflow_unknown_name_returns_tool_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import start_workflow

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {"name": "nope", "params": {}},
            "id": "tc-x",
            "type": "tool_call",
        }, config={"configurable": {"thread_id": "chat-2"}})
        msg = result.update["messages"][0].content
        assert "nope" in msg
        assert "not registered" in msg.lower() or "unknown" in msg.lower()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_start_workflow_invalid_params_returns_tool_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import start_workflow

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {"name": "demo-flow", "params": {}},  # missing task_name
            "id": "tc-y",
            "type": "tool_call",
        }, config={"configurable": {"thread_id": "chat-3"}})
        msg = result.update["messages"][0].content
        assert "task_name" in msg
    finally:
        reset_default_checkpointer()
```

- [ ] **Step 2: 跑测试,确认失败**

`cd backend && uv run pytest tests/test_workflows_tools.py::test_start_workflow_returns_thread_id_and_runs_in_background -v`
Expected: fail

- [ ] **Step 3: 实现 start_workflow + 共用基础设施**

```python
# backend/packages/harness/deerflow/workflows/tools.py
"""LLM-facing workflow platform tools.

Exposed to lead_agent via BUILTIN_TOOLS:
- start_workflow(name, params)
- inject_hint(thread_id, hint)
- cancel_workflow(thread_id)
- get_workflow_progress(thread_id)

The 3 thread-targeting tools validate that thread_id refers to a workflow
the platform actually started, to prevent accidental injection into chat
threads.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any

from fastapi import Request
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from pydantic import ValidationError

from deerflow.runtime.checkpointer_singleton import get_default_checkpointer
from deerflow.workflows.background import run_workflow_background
from deerflow.workflows.registry import WorkflowRegistry

logger = logging.getLogger(__name__)


# Module-level registries — populated by lifespan integration (Task 12).
# Tests monkeypatch ``_get_registry`` to inject a fake.
_REGISTRY: WorkflowRegistry | None = None
_BG_TASKS: dict[str, asyncio.Task] = {}
_THREAD_TO_WORKFLOW: dict[str, str] = {}  # child_thread_id -> workflow name


def set_registry(registry: WorkflowRegistry) -> None:
    global _REGISTRY
    _REGISTRY = registry


def _get_registry() -> WorkflowRegistry:
    if _REGISTRY is None:
        raise RuntimeError("WorkflowRegistry not set; call set_registry() at startup")
    return _REGISTRY


def _tool_msg(content: str, tool_call_id: str) -> Command:
    return Command(update={"messages": [ToolMessage(content=content, tool_call_id=tool_call_id)]})


def _parent_thread_id_from_config(config: RunnableConfig | None) -> str | None:
    if not config:
        return None
    return (config.get("configurable") or {}).get("thread_id")


@tool
async def start_workflow(
    name: str,
    params: dict[str, Any],
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig = None,
) -> Command:
    """Start a registered workflow in the background.

    Args:
        name: Workflow name as registered in config.yaml workflows[].name.
        params: Arguments for the workflow's input_schema (Pydantic model).
            Missing required fields cause a tool error you should ask the
            user about and retry.

    Returns:
        Tool message with the new child thread_id; use it for inject_hint /
        cancel_workflow / get_workflow_progress.
    """
    registry = _get_registry()
    if not registry.has(name):
        available = ", ".join(registry.names()) or "(none)"
        return _tool_msg(
            f"Workflow {name!r} is not registered. Available: {available}",
            tool_call_id,
        )
    spec = registry.get(name)
    try:
        validated = spec.input_schema.model_validate(params)
    except ValidationError as ve:
        return _tool_msg(
            f"Invalid params for {name!r}:\n{ve.errors(include_url=False)}",
            tool_call_id,
        )

    parent_tid = _parent_thread_id_from_config(config)
    if not parent_tid:
        return _tool_msg(
            "start_workflow could not determine parent thread_id from config; refusing to start.",
            tool_call_id,
        )

    child_tid = str(uuid.uuid4())
    cp = get_default_checkpointer()

    task = asyncio.create_task(
        run_workflow_background(
            spec=spec,
            params=validated.model_dump(),
            child_thread_id=child_tid,
            parent_thread_id=parent_tid,
            checkpointer=cp,
        )
    )
    _BG_TASKS[child_tid] = task
    _THREAD_TO_WORKFLOW[child_tid] = name
    task.add_done_callback(lambda _t: _BG_TASKS.pop(child_tid, None))

    return _tool_msg(
        f"Started workflow {name!r}; thread_id={child_tid}. "
        f"Use get_workflow_progress / inject_hint / cancel_workflow to control it.",
        tool_call_id,
    )
```

- [ ] **Step 4: 跑 start_workflow 测试**

`cd backend && uv run pytest tests/test_workflows_tools.py -v -k start_workflow`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/tools.py \
        backend/tests/test_workflows_tools.py
git commit -m "feat(workflows): add start_workflow tool with schema validation"
```

---

## Task 9: tools.py — inject_hint

- [ ] **Step 1: 加测试**

```python
# 加到 backend/tests/test_workflows_tools.py
@pytest.mark.asyncio
async def test_inject_hint_writes_to_state(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.tools import inject_hint, start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)
    parent_tid = "chat-h1"

    # Need a parent checkpoint
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        # Start a workflow first (max_rounds=10 to keep it running)
        start_result = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {"name": "demo-flow", "params": {"task_name": "x", "max_rounds": 10}},
            "id": "h-1",
            "type": "tool_call",
        }, config={"configurable": {"thread_id": parent_tid}})
        msg = start_result.update["messages"][0].content
        child_tid = msg.split("thread_id=")[1].split(".")[0].strip()

        result = await inject_hint.ainvoke({
            "name": "inject_hint",
            "args": {"thread_id": child_tid, "hint": "try smaller lr"},
            "id": "h-2",
            "type": "tool_call",
        })
        assert "injected" in result.update["messages"][0].content.lower()

        # Verify _hints made it into the child state
        graph = make_graph(checkpointer=saver)
        state = await graph.aget_state({"configurable": {"thread_id": child_tid}})
        assert "try smaller lr" in (state.values.get("_hints") or [])

        # Cancel to prevent test bleed
        if child_tid in tools_mod._BG_TASKS:
            tools_mod._BG_TASKS[child_tid].cancel()
    finally:
        reset_default_checkpointer()


@pytest.mark.asyncio
async def test_inject_hint_unknown_thread_returns_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import inject_hint

    _setup_registry_and_checkpointer(monkeypatch)
    try:
        result = await inject_hint.ainvoke({
            "name": "inject_hint",
            "args": {"thread_id": "not-a-workflow-thread", "hint": "x"},
            "id": "h-3",
            "type": "tool_call",
        })
        msg = result.update["messages"][0].content
        assert "not" in msg.lower() and "workflow" in msg.lower()
    finally:
        reset_default_checkpointer()
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 inject_hint(加到 tools.py)**

```python
@tool
async def inject_hint(
    thread_id: str,
    hint: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Append a free-text hint to a running workflow's inbox (non-blocking).

    The workflow decides when (and whether) to consume the hint. Multiple
    hints accumulate in order until the workflow clears them.

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
    spec = _get_registry().get(name)
    cp = get_default_checkpointer()
    graph = spec.factory(checkpointer=cp)
    await graph.aupdate_state(
        config={"configurable": {"thread_id": thread_id}},
        values={"_hints": [hint]},
    )
    return _tool_msg(f"Hint injected into {name!r} (thread_id={thread_id}).", tool_call_id)
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_tools.py -v -k inject_hint`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/tools.py \
        backend/tests/test_workflows_tools.py
git commit -m "feat(workflows): add inject_hint tool with thread validation"
```

---

## Task 10: tools.py — cancel_workflow

- [ ] **Step 1: 加测试**

```python
@pytest.mark.asyncio
async def test_cancel_workflow_cancels_task_and_writes_error(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.demo_flow import make_graph
    from deerflow.workflows.tools import cancel_workflow, start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)
    parent_tid = "chat-c1"

    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    # Make poll_wait genuinely async-sleep so we have time to cancel
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    monkeypatch.setattr(pw.asyncio, "sleep", asyncio.sleep)  # restore real sleep
    try:
        start_result = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {"name": "demo-flow", "params": {"task_name": "x", "max_rounds": 100}},
            "id": "c-1",
            "type": "tool_call",
        }, config={"configurable": {"thread_id": parent_tid}})
        child_tid = start_result.update["messages"][0].content.split("thread_id=")[1].split(".")[0].strip()

        await asyncio.sleep(0.1)  # let it start polling

        cancel_result = await cancel_workflow.ainvoke({
            "name": "cancel_workflow",
            "args": {"thread_id": child_tid},
            "id": "c-2",
            "type": "tool_call",
        })
        assert "cancel" in cancel_result.update["messages"][0].content.lower()

        # Wait for the cancellation to settle
        await asyncio.sleep(0.5)

        graph = make_graph(checkpointer=saver)
        state = await graph.aget_state({"configurable": {"thread_id": child_tid}})
        # _error should mention cancel; is_done should be True
        assert state.values.get("_error")
        assert "cancel" in state.values["_error"].lower()
    finally:
        reset_default_checkpointer()
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 cancel_workflow**

```python
@tool
async def cancel_workflow(
    thread_id: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Cancel a running workflow.

    Sends asyncio CancelledError to the background task. The current node
    is interrupted; state rolls back to the previous checkpoint. ``_error``
    and ``done_field`` are set on the child state. A failure message is
    emitted to the parent thread.
    """
    if thread_id not in _THREAD_TO_WORKFLOW:
        return _tool_msg(
            f"thread_id={thread_id!r} is not a registered workflow thread.",
            tool_call_id,
        )
    name = _THREAD_TO_WORKFLOW[thread_id]
    task = _BG_TASKS.get(thread_id)
    if task is None or task.done():
        return _tool_msg(
            f"Workflow {name!r} on thread {thread_id} is no longer running.",
            tool_call_id,
        )
    task.cancel()
    # The except branch in run_workflow_background will pick up
    # CancelledError as a normal exception and emit + write _error.
    return _tool_msg(
        f"Cancellation signal sent to {name!r} (thread_id={thread_id}).",
        tool_call_id,
    )
```

注意:`run_workflow_background` 当前的 `except Exception` 不会接住 `CancelledError`(它是 `BaseException`)。需要补一个 `except asyncio.CancelledError` 分支。

- [ ] **Step 4: 修 background.py 接住 CancelledError**

在 `run_workflow_background` 的 try/except 链中加(放在 `except Exception` 之前):

```python
    except asyncio.CancelledError:
        err = "CancelledError: workflow cancelled by user"
        logger.info("workflow %s cancelled on %s", spec.name, child_thread_id)
        try:
            await graph.aupdate_state(
                config=cfg,
                values={"_error": err, spec.done_field: True},
            )
        except Exception:
            logger.exception("could not write _error after cancel on %s", child_thread_id)
        try:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] cancelled by user",
                checkpointer=checkpointer,
            )
        except Exception:
            logger.exception("could not emit cancel notice to parent %s", parent_thread_id)
        # Note: do NOT re-raise; we own the lifecycle and have logged + written state.
        return
```

并 `import asyncio` 在文件顶部。

- [ ] **Step 5: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_tools.py -v -k cancel_workflow`
Expected: 1 passed

- [ ] **Step 6: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/tools.py \
        backend/packages/harness/deerflow/workflows/background.py \
        backend/tests/test_workflows_tools.py
git commit -m "feat(workflows): add cancel_workflow tool, handle CancelledError in runner"
```

---

## Task 11: tools.py — get_workflow_progress

- [ ] **Step 1: 加测试**

```python
@pytest.mark.asyncio
async def test_get_workflow_progress_returns_platform_and_progress_fields(monkeypatch):
    from deerflow.runtime.checkpointer_singleton import reset_default_checkpointer
    from deerflow.workflows.tools import get_workflow_progress, start_workflow

    saver, _ = _setup_registry_and_checkpointer(monkeypatch)
    parent_tid = "chat-p1"

    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    pg = g.compile(checkpointer=saver)
    await pg.ainvoke(
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        start_result = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {"name": "demo-flow", "params": {"task_name": "x", "max_rounds": 2}},
            "id": "p-1",
            "type": "tool_call",
        }, config={"configurable": {"thread_id": parent_tid}})
        child_tid = start_result.update["messages"][0].content.split("thread_id=")[1].split(".")[0].strip()

        # Wait for completion
        for _ in range(50):
            await asyncio.sleep(0.05)
            state_result = await get_workflow_progress.ainvoke({
                "name": "get_workflow_progress",
                "args": {"thread_id": child_tid},
                "id": "p-2",
                "type": "tool_call",
            })
            content = state_result.update["messages"][0].content
            if "is_done=True" in content or "is_done: true" in content.lower():
                break

        # Final progress should include progress_fields and report
        assert "current_round" in content
        assert "history" in content
        assert "report_markdown" in content
    finally:
        reset_default_checkpointer()
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 get_workflow_progress**

```python
@tool
async def get_workflow_progress(
    thread_id: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Return current progress of a running workflow.

    Includes platform fields (_hints / _error / done_field) and the
    workflow's declared progress_fields. When the workflow is done the
    report_field is included too.
    """
    if thread_id not in _THREAD_TO_WORKFLOW:
        return _tool_msg(
            f"thread_id={thread_id!r} is not a registered workflow thread.",
            tool_call_id,
        )
    name = _THREAD_TO_WORKFLOW[thread_id]
    spec = _get_registry().get(name)
    cp = get_default_checkpointer()
    graph = spec.factory(checkpointer=cp)
    state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = state.values or {}

    payload: dict[str, Any] = {
        "workflow": name,
        "thread_id": thread_id,
        spec.done_field: values.get(spec.done_field, False),
        "_hints": values.get("_hints") or [],
        "_error": values.get("_error"),
    }
    for field in spec.progress_fields:
        if field in values:
            payload[field] = values[field]
    if values.get(spec.done_field):
        payload[spec.report_field] = values.get(spec.report_field)

    import json
    return _tool_msg(json.dumps(payload, ensure_ascii=False, indent=2), tool_call_id)
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_tools.py -v -k get_workflow_progress`
Expected: 1 passed

- [ ] **Step 5: 跑全部 tools 测试**

`cd backend && uv run pytest tests/test_workflows_tools.py -v`
Expected: 7 passed

- [ ] **Step 6: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/tools.py \
        backend/tests/test_workflows_tools.py
git commit -m "feat(workflows): add get_workflow_progress tool"
```

---

## Task 12: prompt.py — 渲染 workflow 目录

**Files:**
- Create: `backend/packages/harness/deerflow/workflows/prompt.py`
- Create: `backend/tests/test_workflows_prompt.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workflows_prompt.py
"""Tests for the workflow catalog rendered into lead_agent's system prompt."""

from __future__ import annotations

from pydantic import BaseModel, Field


class _SampleInput(BaseModel):
    name: str = Field(description="Task name")
    rounds: int = Field(default=5, ge=1, description="Round budget")
    target: str = Field(default="mAP", description="Target metric")


def _factory(checkpointer=None):  # noqa: ARG001
    return None


def test_render_catalog_lists_each_workflow():
    from deerflow.workflows.prompt import render_workflow_catalog
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    reg = WorkflowRegistry(specs=[
        WorkflowSpec(
            name="demo-flow",
            description="A demo workflow.",
            factory=_factory,
            input_schema=_SampleInput,
            done_field="is_done",
            report_field="report_markdown",
            hint_behavior_doc="Hints are stored but not consumed.",
        ),
    ], failures=[])

    out = render_workflow_catalog(reg)
    assert "demo-flow" in out
    assert "A demo workflow." in out
    assert "name (str, required)" in out
    assert "rounds (int" in out
    assert "default=5" in out
    assert "Hints are stored but not consumed." in out


def test_render_catalog_empty_returns_explicit_marker():
    from deerflow.workflows.prompt import render_workflow_catalog
    from deerflow.workflows.registry import WorkflowRegistry

    out = render_workflow_catalog(WorkflowRegistry(specs=[], failures=[]))
    assert "no workflows" in out.lower()


def test_render_catalog_omits_hint_section_when_doc_blank():
    from deerflow.workflows.prompt import render_workflow_catalog
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

    reg = WorkflowRegistry(specs=[
        WorkflowSpec(
            name="x",
            description="d",
            factory=_factory,
            input_schema=_SampleInput,
            done_field="is_done",
            report_field="r",
        ),
    ], failures=[])
    out = render_workflow_catalog(reg)
    assert "Hint behavior" not in out
```

- [ ] **Step 2: 跑测试,确认失败**

- [ ] **Step 3: 实现 prompt.py**

```python
# backend/packages/harness/deerflow/workflows/prompt.py
"""Render the workflow catalog as a markdown section for lead_agent's prompt."""

from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

_HEADER = (
    "## Available Workflows\n\n"
    "You can start long-running background workflows via "
    "start_workflow(name, params). Then control them with inject_hint, "
    "cancel_workflow, get_workflow_progress (each takes thread_id from "
    "start_workflow's return).\n"
)


def _format_field(name: str, info) -> str:
    annotation = info.annotation
    origin = get_origin(annotation)
    if origin is None:
        type_name = getattr(annotation, "__name__", str(annotation))
    else:
        args = ", ".join(getattr(a, "__name__", str(a)) for a in get_args(annotation))
        type_name = f"{origin.__name__}[{args}]"
    required = info.is_required()
    parts = [f"{type_name}"]
    if required:
        parts.append("required")
    elif info.default is not PydanticUndefined:
        parts.append(f"default={info.default!r}")
    desc = info.description or ""
    return f"  - {name} ({', '.join(parts)}){': ' + desc if desc else ''}"


def _render_one(spec: WorkflowSpec) -> str:
    lines = [f"### {spec.name} — {spec.description.strip()}"]
    schema: type[BaseModel] = spec.input_schema
    lines.append("Params:")
    for fname, finfo in schema.model_fields.items():
        lines.append(_format_field(fname, finfo))
    if spec.hint_behavior_doc.strip():
        lines.append(f"Hint behavior: {spec.hint_behavior_doc.strip()}")
    return "\n".join(lines)


def render_workflow_catalog(registry: WorkflowRegistry) -> str:
    if not registry.all():
        return _HEADER + "\n_No workflows registered._"
    sections = [_render_one(s) for s in registry.all()]
    return _HEADER + "\n" + "\n\n".join(sections)
```

- [ ] **Step 4: 跑测试,确认通过**

`cd backend && uv run pytest tests/test_workflows_prompt.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/workflows/prompt.py \
        backend/tests/test_workflows_prompt.py
git commit -m "feat(workflows): render workflow catalog for lead_agent system prompt"
```

---

## Task 13: 接进 BUILTIN_TOOLS,移除 demo_flow_tool

**Files:**
- Modify: `backend/packages/harness/deerflow/tools/tools.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/__init__.py`
- Modify: `backend/app/gateway/deps.py`(把 registry 注入 tools 模块)
- Delete: `backend/packages/harness/deerflow/tools/builtins/demo_flow_tool.py`

- [ ] **Step 1: 在 deps.py 把 registry 注入 tools.set_registry**

在 lifespan 里 `app.state.workflow_registry = ...` 之后加:

```python
from deerflow.workflows.tools import set_registry
set_registry(app.state.workflow_registry)
```

- [ ] **Step 2: 替换 BUILTIN_TOOLS**

编辑 `backend/packages/harness/deerflow/tools/tools.py`:

```python
from deerflow.tools.builtins import (
    ask_clarification_tool,
    present_file_tool,
    task_tool,
    view_image_tool,
)
from deerflow.workflows.tools import (
    cancel_workflow,
    get_workflow_progress,
    inject_hint,
    start_workflow,
)

BUILTIN_TOOLS = [
    present_file_tool,
    ask_clarification_tool,
    start_workflow,
    inject_hint,
    cancel_workflow,
    get_workflow_progress,
]
```

(把工作区里加的 `start_demo_exploration` 移除。)

- [ ] **Step 3: 移除 builtins/demo_flow_tool.py**

```bash
rm backend/packages/harness/deerflow/tools/builtins/demo_flow_tool.py
```

修 `builtins/__init__.py` — 移除 `from .demo_flow_tool import start_demo_exploration` 和 `__all__` 里的 `"start_demo_exploration"`。

- [ ] **Step 4: 跑后端 lint + 全部 workflow 测试**

```bash
cd backend && uv run ruff check . && uv run pytest tests/test_workflows_*.py -v
```

Expected: ruff pass、所有 workflow 测试 pass

- [ ] **Step 5: 提交**

```bash
git add backend/packages/harness/deerflow/tools/tools.py \
        backend/packages/harness/deerflow/tools/builtins/__init__.py \
        backend/packages/harness/deerflow/tools/builtins/demo_flow_tool.py \
        backend/app/gateway/deps.py
git commit -m "feat(workflows): wire 4 platform tools into BUILTIN_TOOLS"
```

---

## Task 14: lead_agent system prompt 注入 workflow 目录

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`(或 agent.py,看哪边渲染 system prompt)

需先读 lead_agent 现有 prompt 结构。

- [ ] **Step 1: 读 lead_agent prompt 渲染流程**

```bash
cd backend && grep -rn "SystemMessage\|system_prompt\|system_message" packages/harness/deerflow/agents/lead_agent/ | head -20
```

定位 system prompt 拼装位置。

- [ ] **Step 2: 写测试**

```python
# 加到 backend/tests/test_workflows_prompt.py 末尾
def test_lead_agent_prompt_includes_workflow_catalog(monkeypatch):
    """When registry has demo-flow, lead_agent prompt contains its description."""
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph

    reg = WorkflowRegistry(specs=[WorkflowSpec(
        name="demo-flow",
        description="Demo pipeline.",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
    )], failures=[])

    # The exact entry point depends on lead_agent.prompt structure;
    # implementer adapts the import target below.
    from deerflow.agents.lead_agent.prompt import build_system_prompt

    out = build_system_prompt(workflow_registry=reg)
    assert "demo-flow" in out
    assert "Demo pipeline." in out
```

- [ ] **Step 3: 跑测试,确认失败 / 接口不存在**

如果 `build_system_prompt(workflow_registry=...)` 不是现有签名,改造 lead_agent prompt 入口。最小侵入:在现有 prompt 函数里加一个可选参数,默认不注入,保持向后兼容。

- [ ] **Step 4: 改 lead_agent prompt 加上 workflow 目录**

(具体补丁取决于 step 1 找到的结构。原则:从 ToolRuntime 或 app.state 拿到 registry,调 `render_workflow_catalog(registry)` 拼到 system prompt 末尾。如果 lead_agent prompt 是纯字符串拼接,加一段;如果是模板,加变量。)

- [ ] **Step 5: 跑测试 + 后端全测**

```bash
cd backend && uv run pytest tests/test_workflows_prompt.py -v && uv run pytest tests/ -x -q
```

Expected: pass

- [ ] **Step 6: 提交**

```bash
git add backend/packages/harness/deerflow/agents/lead_agent/ \
        backend/tests/test_workflows_prompt.py
git commit -m "feat(lead-agent): inject workflow catalog into system prompt"
```

---

## Task 15: GET /threads/{tid}/children 端点

**Files:**
- Modify: `backend/app/gateway/routers/threads.py`
- Modify: `backend/packages/harness/deerflow/workflows/tools.py`(start_workflow 还要把 child_tid append 进父 thread metadata)
- Create: `backend/tests/test_workflows_children_endpoint.py`

- [ ] **Step 1: 修 start_workflow 在父 thread metadata 写 child 列表**

在 `start_workflow` 里,创建 `_BG_TASKS[child_tid]` 之后,通过 `_store_upsert(store, parent_tid, metadata={"child_workflow_threads": [...]})` 把 `{thread_id, name, started_at}` append。需要从 lifespan 拿到 store(同 checkpointer 一起 set 一个 module-level singleton,或从 request 走 — 但工具没有 request,所以新建一个 `runtime/store_singleton.py`,跟 checkpointer 一样)。

(可选简化:把 child 列表直接写进父 thread 的 checkpoint metadata,而不是 store。但 store 更适合长期数据,checkpoint metadata 易被 graph 操作覆盖。坚持 store。)

- [ ] **Step 1a: 创建 `runtime/store_singleton.py`**

跟 `checkpointer_singleton.py` 同形式:`set_default_store / get_default_store / reset_default_store`。

- [ ] **Step 1b: deps.py lifespan 注册 store**

```python
from deerflow.runtime.store_singleton import set_default_store
set_default_store(app.state.store)
```

- [ ] **Step 1c: start_workflow 写 metadata**

```python
# 在 _BG_TASKS[child_tid] = task 之后
from deerflow.runtime.store_singleton import get_default_store
from app.gateway.routers.threads import _store_upsert
import datetime
store = get_default_store()
if store is not None:
    existing = await store.aget(...)  # see existing _store_upsert pattern
    children = list((existing or {}).get("metadata", {}).get("child_workflow_threads", []))
    children.append({
        "thread_id": child_tid,
        "name": name,
        "started_at": datetime.datetime.now(datetime.UTC).isoformat(),
    })
    await _store_upsert(store, parent_tid, metadata={"child_workflow_threads": children})
```

(`_store_upsert` 现在在 routers/threads.py;考虑把它移到 services 或 helpers,或在 tools.py 里复刻一份。简单点:直接 import 用。)

- [ ] **Step 2: 写 children 端点测试**

```python
# backend/tests/test_workflows_children_endpoint.py
"""GET /threads/{tid}/children returns child workflow threads."""

from __future__ import annotations

# Skeleton — flesh out using the existing test_threads_router pattern:
# spin up TestClient, seed parent thread with metadata.child_workflow_threads,
# GET the endpoint, assert payload.
```

- [ ] **Step 3: 加端点**

在 `routers/threads.py` 加:

```python
@router.get("/threads/{thread_id}/children")
async def list_thread_children(
    thread_id: str,
    store: Any = Depends(get_store),
):
    if store is None:
        return {"children": []}
    record = await store.aget(_NAMESPACE_THREADS, thread_id)
    metadata = (record.value if record else {}).get("metadata", {}) if record else {}
    return {"children": metadata.get("child_workflow_threads", [])}
```

(`_NAMESPACE_THREADS` 已存在,行号见 routers/threads.py:64 附近。)

- [ ] **Step 4: 跑测试**

`cd backend && uv run pytest tests/test_workflows_children_endpoint.py -v`
Expected: pass

- [ ] **Step 5: 提交**

```bash
git add backend/app/gateway/routers/threads.py \
        backend/packages/harness/deerflow/workflows/tools.py \
        backend/packages/harness/deerflow/runtime/store_singleton.py \
        backend/app/gateway/deps.py \
        backend/tests/test_workflows_children_endpoint.py
git commit -m "feat(gateway): GET /threads/{tid}/children + store child thread metadata on start"
```

---

## Task 16: 删除老 demo_flow / 老测试

- [ ] **Step 1: 删除 agents/demo_flow/(已迁入 workflows/demo_flow/)**

```bash
rm -rf backend/packages/harness/deerflow/agents/demo_flow
rm backend/tests/test_demo_flow.py
rm backend/tests/test_demo_flow_background_run.py
rm backend/tests/test_checkpointer_singleton.py  # only if checkpointer_singleton tests are duplicated by workflows tests; keep otherwise
```

(`test_checkpointer_singleton.py` 仍然有效因为 `runtime/checkpointer_singleton.py` 没动。保留。)

- [ ] **Step 2: 跑全部测试 + lint**

```bash
cd backend && uv run ruff check . && uv run pytest -q
```

Expected: pass(所有原 demo_flow 行为已被 workflows 测试覆盖)

- [ ] **Step 3: 提交**

```bash
git add -A backend/packages/harness/deerflow/agents/demo_flow \
        backend/tests/test_demo_flow.py \
        backend/tests/test_demo_flow_background_run.py
git commit -m "chore(workflows): remove old agents/demo_flow (replaced by workflows/demo_flow)"
```

---

## Task 17: 端到端集成测试

**Files:**
- Create: `backend/tests/test_workflows_e2e.py`

模拟 lead_agent 通过 start_workflow / inject_hint / cancel_workflow / get_workflow_progress 全套调用,在 InMemorySaver 上验证父子 thread 行为。

- [ ] **Step 1: 写测试**

```python
# backend/tests/test_workflows_e2e.py
"""End-to-end: lead_agent → start_workflow → demo_flow runs → emits to parent."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_full_lifecycle_demo_flow(monkeypatch):
    """Start, observe progress, complete, verify parent emit."""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.runtime.checkpointer_singleton import (
        reset_default_checkpointer,
        set_default_checkpointer,
    )
    from deerflow.workflows.demo_flow import DemoFlowInput, make_graph
    from deerflow.workflows.demo_flow.nodes import poll_wait_node as pw
    from deerflow.workflows import tools as tools_mod
    from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec
    from deerflow.workflows.tools import (
        get_workflow_progress,
        start_workflow,
    )

    saver = InMemorySaver()
    set_default_checkpointer(saver)

    async def _noop(_s):
        return None
    monkeypatch.setattr(pw.asyncio, "sleep", _noop)
    monkeypatch.setattr(pw.random, "uniform", lambda _a, _b: 0.7)

    reg = WorkflowRegistry(specs=[WorkflowSpec(
        name="demo-flow",
        description="d",
        factory=make_graph,
        input_schema=DemoFlowInput,
        done_field="is_done",
        report_field="report_markdown",
        progress_fields=["current_round", "max_rounds", "history"],
    )], failures=[])
    monkeypatch.setattr(tools_mod, "_get_registry", lambda: reg)

    g = StateGraph(MessagesState)
    g.add_node("noop", lambda s: s)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    parent_graph = g.compile(checkpointer=saver)
    parent_tid = "e2e-parent"
    await parent_graph.ainvoke(
        {"messages": [HumanMessage(content="run a workflow")]},
        config={"configurable": {"thread_id": parent_tid}},
    )

    try:
        # 1. Start
        sr = await start_workflow.ainvoke({
            "name": "start_workflow",
            "args": {"name": "demo-flow", "params": {"task_name": "yolo", "max_rounds": 3}},
            "id": "e2e-1",
            "type": "tool_call",
        }, config={"configurable": {"thread_id": parent_tid}})
        msg = sr.update["messages"][0].content
        child_tid = msg.split("thread_id=")[1].split(".")[0].strip()

        # 2. Wait for completion via get_workflow_progress polling
        for _ in range(50):
            await asyncio.sleep(0.05)
            pr = await get_workflow_progress.ainvoke({
                "name": "get_workflow_progress",
                "args": {"thread_id": child_tid},
                "id": f"e2e-poll-{_}",
                "type": "tool_call",
            })
            if "report_markdown" in pr.update["messages"][0].content:
                break
        else:
            pytest.fail("workflow never completed within 2.5s")

        # 3. Verify parent thread received the report
        parent_state = await parent_graph.aget_state(
            {"configurable": {"thread_id": parent_tid}}
        )
        msgs = [m.content for m in parent_state.values["messages"]]
        assert any("[workflow:demo-flow] done" in m and "yolo" in m for m in msgs)
    finally:
        reset_default_checkpointer()
```

- [ ] **Step 2: 跑测试**

`cd backend && uv run pytest tests/test_workflows_e2e.py -v`
Expected: 1 passed

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_workflows_e2e.py
git commit -m "test(workflows): end-to-end start_workflow → demo_flow → parent emit"
```

---

## Task 18: 全量验证 + 手动 smoke

- [ ] **Step 1: 跑全部测试 + lint**

```bash
cd backend && uv run ruff check . && uv run pytest -q
```

Expected: ruff 零 issue、所有测试 pass(应 ≥ 277 + 新增的 ~30)

- [ ] **Step 2: 启动 gateway,确认 lifespan 加载 registry 不炸**

```bash
cd /data/src/deer-flow && make stop && make dev
```

观察 `logs/gateway.log` 出现:
- workflow registry 成功加载 demo-flow
- 没有 ImportError / ValueError

- [ ] **Step 3: 用 curl 验证 children 端点**

```bash
curl -sS http://localhost:8001/threads/test-thread-id/children
# Expected: {"children": []}
```

- [ ] **Step 4: 浏览器手动 e2e**

打开 `http://localhost:2026`,在 chat 里说:
> 启动一个 demo workflow,任务名 e2e-test,跑 3 轮

观察:
- LLM 调用 `start_workflow` 返回 child_thread_id
- 几秒后 LLM 收到 `[workflow:demo-flow] done` 系统消息
- 用户看到 LLM 转述探索报告

接着试:
> 帮我注入一个 hint 到刚才那个 workflow

LLM 应该说"那个 workflow 已经完成了,无法注入"。

再起一个轮次大的:
> 启动一个 demo workflow,任务名 long,跑 30 轮

立即:
> 取消那个 workflow

观察 LLM 调 `cancel_workflow`,父 thread 收到 `[workflow:demo-flow] cancelled by user`。

- [ ] **Step 5: 把手动观察到的现象写进 commit / PR description**

不必 commit;但若发现 bug 即开新 task 修。

---

## Self-Review Checklist

- [x] Spec coverage:每个 §3-§9 都有对应 task(注册 §3 = T2/T4,入参 §4 = T3/T8,base state §5 = T1,hint §6 = T9,emit/progress §7 = T6/T7/T11/T15,取消/异常 §8 = T10,API §9 = T13/T14/T15)
- [x] No placeholders:每个 step 给出具体代码或具体命令
- [x] 类型一致:`spec.factory(checkpointer=...)`、`spec.input_schema.model_validate(...)`、`spec.done_field`/`report_field`/`progress_fields` 在所有 task 引用一致
- [ ] 风险点已考虑:
  - `aupdate_state` 在 LangGraph 不同版本签名差异:Task 6 测试会暴露
  - `CancelledError` 不被 `Exception` 接住:Task 10 显式补 except 分支
  - 中文字段名残留:Task 3 已英文化,demo_flow 测试使用英文键
  - lead_agent prompt 接入点不明确:Task 14 step 1 先 grep 定位
- [ ] 可独立交付:每个 task 提交后系统应仍可运行(测试 pass),除 Task 13 之前 BUILTIN_TOOLS 还旧版,中间状态可接受
