# Remove Sandbox Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the multi-backend sandbox abstraction (bwrap + AioSandbox + virtual `/mnt/...` paths) into a single host-direct implementation, while keeping `Sandbox` as a thin filesystem façade for tools.

**Architecture:** `Sandbox` abstract class survives as a tools-facing façade; below it only one implementation (`LocalSandbox`) remains, driven by host syscalls. `SandboxProvider` lifecycle, `SandboxMiddleware`, bwrap, AioSandbox, the virtual `/mnt/user-data`/`/mnt/skills` path system, `sandbox.mounts`/`sandbox.allow_host_bash`/Docker-related config fields all disappear. Prompts and skill markdown switch from `/mnt/...` literals to real host paths injected via four template variables (`{workspace_path}`, `{uploads_path}`, `{outputs_path}`, `{skills_path}`).

**Tech Stack:** Python 3.12 + LangGraph/LangChain agents middleware; FastAPI gateway; Next.js frontend (minimal touch).

**Spec:** `docs/superpowers/specs/2026-05-05-remove-sandbox-isolation-design.md`

---

## File Structure

### Deleted entirely
- `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`
- `backend/packages/harness/deerflow/sandbox/middleware.py`
- `backend/packages/harness/deerflow/sandbox/security.py`
- `backend/packages/harness/deerflow/sandbox/local/bwrap_runner.py`
- `backend/packages/harness/deerflow/sandbox/local/local_sandbox.py` (contents moved)
- `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py`
- `backend/packages/harness/deerflow/sandbox/local/list_dir.py` (moved to `sandbox/list_dir.py`)
- `backend/packages/harness/deerflow/sandbox/local/__init__.py`
- `backend/packages/harness/deerflow/community/aio_sandbox/` (entire directory: `__init__.py`, `aio_sandbox.py`, `aio_sandbox_provider.py`, `backend.py`, `local_backend.py`, `remote_backend.py`, `sandbox_info.py`)
- Test files: `test_aio_sandbox.py`, `test_aio_sandbox_local_backend.py`, `test_aio_sandbox_provider.py`, `test_bwrap_runner.py`, `test_bash_tool_bwrap_wiring.py`, `test_docker_sandbox_mode_detection.py`, `test_local_sandbox_provider_mounts.py`, `test_sandbox_audit_middleware.py`, `test_sandbox_orphan_reconciliation.py`, `test_sandbox_orphan_reconciliation_e2e.py`, `test_sandbox_tools_security.py`

### Moved
- `sandbox/local/local_sandbox.py` → `sandbox/local_sandbox.py` (simplified; no `path_mappings`)
- `sandbox/local/list_dir.py` → `sandbox/list_dir.py`

### Created
- `backend/packages/harness/deerflow/sandbox/local_sandbox.py` — single `LocalSandbox(Sandbox)` impl + `get_sandbox()` singleton
- `backend/tests/test_get_sandbox_singleton.py` — singleton getter test
- `backend/tests/test_legacy_sandbox_config_warning.py` — deprecation warning test
- `backend/tests/test_apply_prompt_template_path_vars.py` — template variable injection test
- `backend/tests/test_artifact_url_compat.py` — backward-compat URL test (already covered by `test_artifacts_router.py` extension)

### Modified
- `backend/packages/harness/deerflow/sandbox/__init__.py` — exposes only `Sandbox` + `get_sandbox`
- `backend/packages/harness/deerflow/sandbox/sandbox.py` — `execute_command` gains `cwd: str | None = None` parameter
- `backend/packages/harness/deerflow/sandbox/tools.py` — drops bwrap branch, drops virtual-path translation helpers, `_DEFAULT_SKILLS_CONTAINER_PATH` and `_ACP_WORKSPACE_VIRTUAL_PATH` constants removed (latter moves to ACP tool)
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` — system prompt template adopts `{workspace_path}`/`{uploads_path}`/`{outputs_path}`/`{skills_path}`; `apply_prompt_template` accepts `thread_data` and `skills_host_path`
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py` — call sites of `apply_prompt_template` pipe through `thread_data`/`skills_host_path`
- `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` — `_build_runtime_middlewares` drops `SandboxMiddleware`
- `backend/packages/harness/deerflow/agents/factory.py` — drops `SandboxMiddleware` from alt pipeline
- `backend/packages/harness/deerflow/agents/thread_state.py` — drops `SandboxState` and `sandbox` field on `ThreadState`
- `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py` — prompt strings switch to real `{uploads_path}` value resolved at runtime
- `backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py` — drop `_skills_container_path`; use real skills host path
- `backend/packages/harness/deerflow/agents/memory/updater.py` — regex no longer looks for `/mnt/user-data/uploads/` literal
- `backend/packages/harness/deerflow/subagents/builtins/general_purpose.py` — prompt rewritten with template vars
- `backend/packages/harness/deerflow/subagents/builtins/bash_agent.py` — prompt rewritten with template vars
- `backend/packages/harness/deerflow/tools/builtins/present_file_tool.py` — accepts host real paths; whitelist via `thread_data.outputs_path`
- `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py` — owns its own `_ACP_WORKSPACE_VIRTUAL_PATH` constant
- `backend/packages/harness/deerflow/tools/builtins/view_image_tool.py` — comment refresh (no `/mnt/...` mention)
- `backend/packages/harness/deerflow/uploads/manager.py` — `upload_artifact_url` and `upload_virtual_path` use new short URL form
- `backend/packages/harness/deerflow/config/sandbox_config.py` — drops Docker-related fields & `VolumeMountConfig`
- `backend/packages/harness/deerflow/config/skills_config.py` — drops `container_path`, `get_skill_container_path`
- `backend/packages/harness/deerflow/config/paths.py` — drops `VIRTUAL_PATH_PREFIX` and `Paths.resolve_virtual_path`
- `backend/packages/harness/deerflow/skills/types.py` — drops `Skill.get_container_path`/`get_container_file_path`
- `backend/app/gateway/routers/artifacts.py` — accepts both new short and legacy `mnt/user-data/...` URL shapes
- `backend/app/gateway/path_utils.py` — adapts to spec's runtime path semantics
- `skills/public/*/SKILL.md` (10 files) — `/mnt/...` literals replaced
- `frontend/src/components/landing/progressive-skills-animation.tsx` — cosmetic literal updated
- `README.md`, `CONTRIBUTING.md`, `docs/**/*.md`, `Makefile`, `.github/copilot-instructions.md`, `config.example.yaml` — any sandbox-isolation/bwrap/Docker references removed
- `frontend/package.json` — no change expected

---

# Stage 1: Delete bwrap dead code (Spec Step 1)

### Task 1.1: Drop bwrap branch from `bash_tool`

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py`
- Test: `backend/tests/test_bash_tool_bwrap_wiring.py` (delete after this task)

- [ ] **Step 1: Write failing test confirming bash routes uniformly through `sandbox.execute_command`**

Add to `backend/tests/test_bash_tool_routing.py` (new file):

```python
from unittest.mock import MagicMock, patch
from deerflow.sandbox.tools import bash_tool

def test_bash_tool_uses_sandbox_execute_command(monkeypatch):
    """bash_tool always delegates to sandbox.execute_command (no bwrap branch)."""
    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "hello"
    fake_runtime = MagicMock()
    fake_runtime.context = {"thread_id": "t1"}
    fake_runtime.state = {"thread_data": {"workspace_path": "/tmp/ws"}}

    with patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=fake_sandbox), \
         patch("deerflow.sandbox.tools.ensure_thread_directories_exist"):
        # Should reach sandbox.execute_command exactly once, regardless of provider
        result = bash_tool.invoke({"runtime": fake_runtime, "description": "test", "command": "echo hi"})

    fake_sandbox.execute_command.assert_called_once()
    assert "hello" in result
```

- [ ] **Step 2: Run test, verify it fails**

```
cd backend && uv run pytest tests/test_bash_tool_routing.py -v
```
Expected: FAIL — `bash_tool` currently routes to `_execute_local_bash_in_bwrap` for local provider.

- [ ] **Step 3: Strip bwrap branch from `bash_tool`**

In `backend/packages/harness/deerflow/sandbox/tools.py`:
- Remove `_execute_local_bash_in_bwrap` function entirely (lines ~994-1038)
- In `bash_tool` (lines ~1041-1086), remove the `if is_local_sandbox(runtime): ... _execute_local_bash_in_bwrap(...)` branch and the `BwrapNotInstalledError` except clause
- Remove `from deerflow.sandbox.local.bwrap_runner import (BwrapMount, BwrapNotInstalledError, execute_bwrap)` at the top

After surgery, `bash_tool` body becomes:

```python
@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """[docstring unchanged]"""
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        try:
            from deerflow.config.app_config import get_app_config
            sandbox_cfg = get_app_config().sandbox
            max_chars = sandbox_cfg.bash_output_max_chars if sandbox_cfg else 20000
        except Exception:
            max_chars = 20000
        return _truncate_bash_output(sandbox.execute_command(command), max_chars)
    except SandboxError as e:
        return f"Error: {e}"
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing command: {_sanitize_error(e, runtime)}"
```

- [ ] **Step 4: Run new test, verify it passes**

```
cd backend && uv run pytest tests/test_bash_tool_routing.py -v
```
Expected: PASS.

- [ ] **Step 5: Delete obsolete bwrap-wiring test**

```bash
rm backend/tests/test_bash_tool_bwrap_wiring.py
```

- [ ] **Step 6: Run full backend tests to confirm nothing else broke (other than bwrap tests still using deleted symbols)**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | tail -30
```
Expected: failures should now be limited to other tests still importing bwrap/`_execute_local_bash_in_bwrap`. Note them; we delete those next task.

- [ ] **Step 7: Commit**

```bash
git add backend/packages/harness/deerflow/sandbox/tools.py \
        backend/tests/test_bash_tool_routing.py \
        backend/tests/test_bash_tool_bwrap_wiring.py
git commit -m "refactor(sandbox): drop bwrap branch from bash_tool"
```

### Task 1.2: Delete `bwrap_runner.py` and its tests

**Files:**
- Delete: `backend/packages/harness/deerflow/sandbox/local/bwrap_runner.py`
- Delete: `backend/tests/test_bwrap_runner.py`

- [ ] **Step 1: Confirm no remaining importers**

```
cd backend && grep -rn "bwrap_runner\|build_bwrap_argv\|execute_bwrap\|BwrapMount\|BwrapNotInstalledError" packages/ app/ tests/ | grep -v test_bwrap_runner.py
```
Expected: no output (or only the file we're about to delete).

- [ ] **Step 2: Delete files**

```bash
rm backend/packages/harness/deerflow/sandbox/local/bwrap_runner.py
rm backend/tests/test_bwrap_runner.py
```

- [ ] **Step 3: Run lint + tests**

```
cd backend && make lint && uv run pytest tests/ -x -q 2>&1 | tail -10
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): delete bwrap runner and tests"
```

---

# Stage 2: Delete host-bash gate (Spec Step 2)

### Task 2.1: Remove `allow_host_bash` gate from bash_tool and bash subagent

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py`
- Modify: `backend/packages/harness/deerflow/subagents/builtins/bash_agent.py` (if it gates on `is_host_bash_allowed`)
- Test: extend `backend/tests/test_bash_tool_routing.py`

- [ ] **Step 1: Add failing test confirming bash works without `allow_host_bash`**

Append to `backend/tests/test_bash_tool_routing.py`:

```python
def test_bash_tool_no_host_bash_gate(monkeypatch):
    """bash_tool runs without checking allow_host_bash config."""
    # No special config setup — the gate must simply not exist.
    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "ok"
    fake_runtime = MagicMock()
    fake_runtime.context = {"thread_id": "t1"}
    fake_runtime.state = {"thread_data": {"workspace_path": "/tmp/ws"}}

    with patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=fake_sandbox), \
         patch("deerflow.sandbox.tools.ensure_thread_directories_exist"):
        result = bash_tool.invoke({"runtime": fake_runtime, "description": "test", "command": "true"})

    assert "ok" in result
    assert "disabled" not in result.lower()
```

- [ ] **Step 2: Run test, verify it fails (gate currently rejects host bash for local provider)**

```
cd backend && uv run pytest tests/test_bash_tool_routing.py::test_bash_tool_no_host_bash_gate -v
```
Expected: FAIL — current code returns `LOCAL_HOST_BASH_DISABLED_MESSAGE`.

- [ ] **Step 3: Strip gate from `bash_tool`**

In `backend/packages/harness/deerflow/sandbox/tools.py`:
- Delete `is_local_sandbox` reference at the top (and import) if unused elsewhere
- Delete `is_host_bash_allowed` import
- Delete `LOCAL_HOST_BASH_DISABLED_MESSAGE` import
- (Anything left over from Task 1.1 — none expected.)

Same for `subagents/builtins/bash_agent.py`: remove `LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE` checks (grep for it first; remove guard logic; bash subagent always available).

- [ ] **Step 4: Run test, verify it passes**

```
cd backend && uv run pytest tests/test_bash_tool_routing.py -v
```

- [ ] **Step 5: Run full backend tests**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | tail -10
```
Expected: only `test_sandbox_tools_security.py` may fail (it tests the gate); we delete it next.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): drop allow_host_bash gate from bash tool and subagent"
```

### Task 2.2: Delete `sandbox/security.py` and gate-related tests

**Files:**
- Delete: `backend/packages/harness/deerflow/sandbox/security.py`
- Delete: `backend/tests/test_sandbox_tools_security.py`

- [ ] **Step 1: Verify no remaining importers**

```
cd backend && grep -rn "from deerflow.sandbox.security\|deerflow.sandbox.security" packages/ app/ tests/
```
Expected: empty.

- [ ] **Step 2: Delete files**

```bash
rm backend/packages/harness/deerflow/sandbox/security.py
rm backend/tests/test_sandbox_tools_security.py
```

- [ ] **Step 3: Run tests**

```
cd backend && make lint && uv run pytest tests/ -x -q 2>&1 | tail -10
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): delete security.py and host-bash gate tests"
```

### Task 2.3: Drop `allow_host_bash` field from `SandboxConfig`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/sandbox_config.py`

- [ ] **Step 1: Delete the field**

In `sandbox_config.py`, delete the `allow_host_bash: bool = Field(...)` field (line ~34). Update the class docstring to no longer mention it.

- [ ] **Step 2: Verify config still loads with old yaml containing `allow_host_bash: true`**

```python
# Add to backend/tests/test_sandbox_config_compat.py (new):
import pytest, yaml
from deerflow.config.sandbox_config import SandboxConfig

def test_legacy_allow_host_bash_field_ignored():
    """SandboxConfig.extra='allow' silently keeps unknown legacy fields."""
    cfg = SandboxConfig.model_validate({"allow_host_bash": True, "bash_output_max_chars": 5000})
    assert cfg.bash_output_max_chars == 5000
    # Field absent on model
    assert not hasattr(cfg, "allow_host_bash") or cfg.__pydantic_extra__.get("allow_host_bash") is True
```

- [ ] **Step 3: Run test**

```
cd backend && uv run pytest tests/test_sandbox_config_compat.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): drop allow_host_bash field from SandboxConfig"
```

---

# Stage 3: Delete AioSandbox (Spec Step 3)

### Task 3.1: Confirm AioSandbox is unreachable from default config and live code

- [ ] **Step 1: Grep for AioSandbox uses outside `community/aio_sandbox/`**

```
cd /data/src/deer-flow && grep -rn "AioSandbox\|aio_sandbox" backend/packages/harness/deerflow --include="*.py" | grep -v "^backend/packages/harness/deerflow/community/aio_sandbox/"
```

Expected list — anything outside the community module is a callsite that needs updating. Likely zero (it's a config-driven optional).

```
cd /data/src/deer-flow && grep -rn "AioSandbox" backend/tests config.example.yaml docker/ docs/ 2>/dev/null
```
Note any references; tests will be deleted in 3.3.

- [ ] **Step 2: No code change here — this is verification. Document findings inline.**

### Task 3.2: Delete `community/aio_sandbox/` directory

**Files:**
- Delete: `backend/packages/harness/deerflow/community/aio_sandbox/` (entire directory: `__init__.py`, `aio_sandbox.py`, `aio_sandbox_provider.py`, `backend.py`, `local_backend.py`, `remote_backend.py`, `sandbox_info.py`)

- [ ] **Step 1: Delete the directory**

```bash
rm -rf backend/packages/harness/deerflow/community/aio_sandbox/
```

- [ ] **Step 2: Run lint to surface dangling imports**

```
cd backend && make lint 2>&1 | head -20
```

If any module imports from `deerflow.community.aio_sandbox`, those are listed; resolve them in the next task.

- [ ] **Step 3: Run unit tests; expect AioSandbox-suite tests to error on import**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | head -30
```

Tests expected to fail (collection-time import error): `test_aio_sandbox.py`, `test_aio_sandbox_local_backend.py`, `test_aio_sandbox_provider.py`, `test_docker_sandbox_mode_detection.py`. Delete them in 3.3.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): delete community/aio_sandbox/ module"
```

### Task 3.3: Delete AioSandbox-related tests

**Files:**
- Delete: `backend/tests/test_aio_sandbox.py`
- Delete: `backend/tests/test_aio_sandbox_local_backend.py`
- Delete: `backend/tests/test_aio_sandbox_provider.py`
- Delete: `backend/tests/test_docker_sandbox_mode_detection.py`

- [ ] **Step 1: Delete files**

```bash
rm backend/tests/test_aio_sandbox.py \
   backend/tests/test_aio_sandbox_local_backend.py \
   backend/tests/test_aio_sandbox_provider.py \
   backend/tests/test_docker_sandbox_mode_detection.py
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | tail -10
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): delete AioSandbox-specific tests"
```

### Task 3.4: Drop AioSandbox/Docker fields from `SandboxConfig`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/sandbox_config.py`

- [ ] **Step 1: Write failing test asserting trimmed schema**

Append to `backend/tests/test_sandbox_config_compat.py`:

```python
def test_sandbox_config_no_docker_fields():
    """SandboxConfig exposes only the three output-truncation fields."""
    cfg = SandboxConfig()
    declared = set(cfg.model_fields.keys())
    assert declared == {
        "bash_output_max_chars",
        "read_file_output_max_chars",
        "ls_output_max_chars",
    }
```

- [ ] **Step 2: Run test, verify failure**

```
cd backend && uv run pytest tests/test_sandbox_config_compat.py::test_sandbox_config_no_docker_fields -v
```
Expected: FAIL.

- [ ] **Step 3: Strip fields from `SandboxConfig`**

In `backend/packages/harness/deerflow/config/sandbox_config.py`, delete:
- `use: str = Field(...)` field — make it implicit; loading still works thanks to `extra="allow"`
- `image`, `port`, `replicas`, `container_prefix`, `idle_timeout`, `mounts`, `environment` fields
- `VolumeMountConfig` class entirely (file-top)
- Update class docstring to drop mentions of Docker/replicas/etc.

After surgery the file should be:

```python
from pydantic import BaseModel, ConfigDict, Field


class SandboxConfig(BaseModel):
    """Config section for sandbox-related runtime knobs.

    Only output-truncation knobs remain; isolation backends and host-side
    safety gates have been removed (see docs/superpowers/specs/2026-05-05-remove-sandbox-isolation-design.md).

    Legacy fields (`use`, `mounts`, `image`, `replicas`, `container_prefix`,
    `idle_timeout`, `environment`, `allow_host_bash`) are silently accepted
    via `extra="allow"` so old config.yaml files keep loading; a startup
    warning is emitted when `use` is non-empty (see app startup hook).
    """

    bash_output_max_chars: int = Field(default=20000, ge=0, description="...")
    read_file_output_max_chars: int = Field(default=50000, ge=0, description="...")
    ls_output_max_chars: int = Field(default=20000, ge=0, description="...")

    model_config = ConfigDict(extra="allow")
```

- [ ] **Step 4: Run test, verify pass**

```
cd backend && uv run pytest tests/test_sandbox_config_compat.py -v
```

- [ ] **Step 5: Run full lint + tests**

```
cd backend && make lint && uv run pytest tests/ -q 2>&1 | tail -10
```

Note any failing tests that read deleted fields (likely `test_local_sandbox_provider_mounts.py` — that test goes away in Task 5.x).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): drop Docker/Aio-specific fields from SandboxConfig"
```

### Task 3.5: Add startup deprecation warning for legacy `sandbox.use`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/app_config.py` (or wherever app config validates at startup)
- Test: `backend/tests/test_legacy_sandbox_config_warning.py` (new)

- [ ] **Step 1: Locate app-config validation seam**

```
cd backend && grep -n "def get_app_config\|class AppConfig" packages/harness/deerflow/config/app_config.py
```

- [ ] **Step 2: Write failing test**

`backend/tests/test_legacy_sandbox_config_warning.py`:

```python
import logging
import pytest
from deerflow.config.app_config import AppConfig


def test_legacy_sandbox_use_emits_warning(caplog):
    """If config.yaml carries a legacy sandbox.use, a single deprecation warning is logged."""
    yaml_data = {
        "sandbox": {"use": "deerflow.community.aio_sandbox:AioSandboxProvider"},
        # ... minimal other required fields if any
    }
    with caplog.at_level(logging.WARNING):
        cfg = AppConfig.model_validate(yaml_data)
        # Trigger whatever startup validation hook surfaces the warning;
        # if validation alone doesn't, call the explicit hook.
        from deerflow.config.app_config import warn_on_legacy_sandbox_use
        warn_on_legacy_sandbox_use(cfg)

    matches = [r for r in caplog.records if "sandbox.use" in r.message]
    assert len(matches) == 1
    assert "no longer supported" in matches[0].message.lower()


def test_no_warning_when_sandbox_use_absent(caplog):
    yaml_data = {"sandbox": {}}
    with caplog.at_level(logging.WARNING):
        cfg = AppConfig.model_validate(yaml_data)
        from deerflow.config.app_config import warn_on_legacy_sandbox_use
        warn_on_legacy_sandbox_use(cfg)

    assert not [r for r in caplog.records if "sandbox.use" in r.message]
```

- [ ] **Step 3: Run test, verify failure**

- [ ] **Step 4: Implement warning hook**

In `backend/packages/harness/deerflow/config/app_config.py`, add:

```python
def warn_on_legacy_sandbox_use(config: "AppConfig") -> None:
    """Log a one-time deprecation warning if legacy sandbox.use is present."""
    extra = getattr(config.sandbox, "__pydantic_extra__", None) or {}
    legacy_use = extra.get("use")
    if legacy_use:
        logging.getLogger(__name__).warning(
            "sandbox.use=%s is no longer supported; sandbox isolation has been removed. "
            "The field will be ignored. Remove it from config.yaml to silence this warning.",
            legacy_use,
        )
```

Wire `warn_on_legacy_sandbox_use(get_app_config())` into the existing app startup path (likely `backend/app/gateway/app.py` startup or `langgraph` boot).

- [ ] **Step 5: Run test, verify pass**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): warn on legacy sandbox.use config"
```

### Task 3.6: Clean `config.example.yaml`

**Files:**
- Modify: `config.example.yaml`

- [ ] **Step 1: Strip legacy sandbox lines**

In `config.example.yaml`, delete any of:
- `sandbox.use`
- `sandbox.allow_host_bash`
- `sandbox.image`
- `sandbox.port`
- `sandbox.replicas`
- `sandbox.container_prefix`
- `sandbox.idle_timeout`
- `sandbox.mounts`
- `sandbox.environment`

Keep the three output-truncation knobs (or remove them too — they have defaults — your call; we keep them as discoverability docs).

- [ ] **Step 2: Diff and confirm minimal**

```
git diff config.example.yaml
```

- [ ] **Step 3: Commit**

```bash
git add config.example.yaml
git commit -m "docs(config): strip Docker/Aio sandbox fields from example yaml"
```

---

# Stage 4: Slim the `Sandbox` abstraction (Spec Step 4)

### Task 4.1: Add `cwd` parameter to `Sandbox.execute_command`

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/sandbox.py`
- Modify: `backend/packages/harness/deerflow/sandbox/local/local_sandbox.py`
- Test: `backend/tests/test_local_sandbox_cwd.py` (new)

- [ ] **Step 1: Write failing test**

`backend/tests/test_local_sandbox_cwd.py`:

```python
import os
from deerflow.sandbox.local.local_sandbox import LocalSandbox

def test_execute_command_honors_cwd(tmp_path):
    sb = LocalSandbox(id="t")
    out = sb.execute_command("pwd", cwd=str(tmp_path))
    assert str(tmp_path) in out

def test_execute_command_default_cwd_unchanged(tmp_path):
    sb = LocalSandbox(id="t")
    out = sb.execute_command("pwd")
    # No cwd ⇒ inherits backend process cwd; just confirm subprocess ran.
    assert os.getcwd() in out
```

- [ ] **Step 2: Run, fail (no cwd parameter exists)**

- [ ] **Step 3: Add `cwd: str | None = None` to `Sandbox.execute_command` ABC + `LocalSandbox.execute_command`; pass through to `subprocess.run(args, cwd=cwd, ...)`.**

- [ ] **Step 4: Run, pass**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(sandbox): add cwd parameter to Sandbox.execute_command"
```

### Task 4.2: Drop `SandboxMiddleware` from middleware chain

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`
- Modify: `backend/packages/harness/deerflow/agents/factory.py`
- Test: `backend/tests/test_middleware_chain_no_sandbox.py` (new)

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_middleware_chain_no_sandbox.py
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

def test_chain_omits_sandbox_middleware():
    chain = build_lead_runtime_middlewares(lazy_init=True)
    cls_names = {type(m).__name__ for m in chain}
    assert "SandboxMiddleware" not in cls_names
    # ThreadDataMiddleware stays
    assert "ThreadDataMiddleware" in cls_names
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: In `tool_error_handling_middleware.py:_build_runtime_middlewares`, delete the `SandboxMiddleware(lazy_init=lazy_init)` line and its import.** Same in `agents/factory.py:189-203` if present.

- [ ] **Step 4: Run, pass**

- [ ] **Step 5: Run full tests**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | tail -10
```

Expect transient failures in tests that introspect chain/state (e.g. `test_sandbox_audit_middleware.py` — addressed in Task 4.5).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): remove SandboxMiddleware from agent chain"
```

### Task 4.3: Drop `SandboxState` from `ThreadState`

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/thread_state.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_thread_state_schema.py
from deerflow.agents.thread_state import ThreadState

def test_thread_state_no_sandbox_field():
    annotations = ThreadState.__annotations__
    assert "sandbox" not in annotations
    # thread_data stays
    assert "thread_data" in annotations
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: In `thread_state.py`, delete the `SandboxState` TypedDict class and the `sandbox: NotRequired[SandboxState | None]` field on `ThreadState`.** Update imports (if `SandboxState` is re-exported anywhere).

- [ ] **Step 4: Find consumers reading `state["sandbox"]`**

```
cd backend && grep -rn "state\[\"sandbox\"\]\|state.get(\"sandbox\"" packages/ app/
```

For each consumer: change to `get_sandbox()` (added in next task) or remove.

- [ ] **Step 5: Run, pass**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): drop SandboxState from ThreadState schema"
```

### Task 4.4: Replace `SandboxProvider` with `get_sandbox()` singleton; flatten `sandbox/local/`

**Files:**
- Create: `backend/packages/harness/deerflow/sandbox/local_sandbox.py` (moved from `sandbox/local/local_sandbox.py`, simplified)
- Create: `backend/packages/harness/deerflow/sandbox/list_dir.py` (moved from `sandbox/local/list_dir.py`)
- Modify: `backend/packages/harness/deerflow/sandbox/__init__.py`
- Delete: `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`
- Delete: `backend/packages/harness/deerflow/sandbox/middleware.py`
- Delete: `backend/packages/harness/deerflow/sandbox/local/` (entire dir)

- [ ] **Step 1: Write failing test for new public API**

```python
# backend/tests/test_get_sandbox_singleton.py
import pytest

def test_get_sandbox_returns_singleton():
    from deerflow.sandbox import get_sandbox, Sandbox
    s1 = get_sandbox()
    s2 = get_sandbox()
    assert s1 is s2
    assert isinstance(s1, Sandbox)


def test_old_get_sandbox_provider_removed():
    """Importing the old API raises ImportError."""
    with pytest.raises(ImportError):
        from deerflow.sandbox import get_sandbox_provider  # noqa
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Move + simplify LocalSandbox**

Move `sandbox/local/local_sandbox.py` → `sandbox/local_sandbox.py` and **strip path mappings**:

```python
# sandbox/local_sandbox.py
import errno, ntpath, os, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path

from deerflow.sandbox.list_dir import list_dir
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.search import GrepMatch, find_glob_matches, find_grep_matches


class LocalSandbox(Sandbox):
    def __init__(self, id: str = "local"):
        super().__init__(id)

    @staticmethod
    def _shell_name(shell: str) -> str:
        return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()

    @staticmethod
    def _is_powershell(shell: str) -> bool:
        return LocalSandbox._shell_name(shell) in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}

    @staticmethod
    def _is_cmd_shell(shell: str) -> bool:
        return LocalSandbox._shell_name(shell) in {"cmd", "cmd.exe"}

    @staticmethod
    def _find_first_available_shell(candidates: tuple[str, ...]) -> str | None:
        for shell in candidates:
            if os.path.isabs(shell):
                if os.path.isfile(shell) and os.access(shell, os.X_OK):
                    return shell
                continue
            shell_from_path = shutil.which(shell)
            if shell_from_path is not None:
                return shell_from_path
        return None

    @staticmethod
    def _get_shell() -> str:
        shell = LocalSandbox._find_first_available_shell(("/bin/zsh", "/bin/bash", "/bin/sh", "sh"))
        if shell is not None:
            return shell
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            shell = LocalSandbox._find_first_available_shell((
                "pwsh", "pwsh.exe", "powershell", "powershell.exe",
                ntpath.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                "cmd.exe",
            ))
            if shell is not None:
                return shell
            raise RuntimeError("No suitable shell executable found.")
        raise RuntimeError("No suitable shell executable found.")

    def execute_command(self, command: str, *, cwd: str | None = None) -> str:
        shell = self._get_shell()
        if os.name == "nt" and self._is_powershell(shell):
            args = [shell, "-NoProfile", "-Command", command]
        elif os.name == "nt" and self._is_cmd_shell(shell):
            args = [shell, "/c", command]
        else:
            args = [shell, "-c", command]
        result = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=600, cwd=cwd)
        output = result.stdout
        if result.stderr:
            output += f"\nStd Error:\n{result.stderr}" if output else result.stderr
        if result.returncode != 0:
            output += f"\nExit Code: {result.returncode}"
        return output if output else "(no output)"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        return list_dir(path, max_depth)

    def read_file(self, path: str) -> str:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise type(e)(e.errno, e.strerror, path) from None

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise type(e)(e.errno, e.strerror, path) from None

    def update_file(self, path: str, content: bytes) -> None:
        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
        except OSError as e:
            raise type(e)(e.errno, e.strerror, path) from None

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200):
        return find_glob_matches(Path(path), pattern, include_dirs=include_dirs, max_results=max_results)

    def grep(self, path: str, pattern: str, *, glob: str | None = None, literal: bool = False, case_sensitive: bool = False, max_results: int = 100):
        return find_grep_matches(Path(path), pattern, glob_pattern=glob, literal=literal, case_sensitive=case_sensitive, max_results=max_results)


_singleton: LocalSandbox | None = None


def get_sandbox() -> Sandbox:
    """Return the process-level Sandbox singleton (host-direct, no isolation)."""
    global _singleton
    if _singleton is None:
        _singleton = LocalSandbox()
    return _singleton


def reset_sandbox_for_tests() -> None:
    """Clear the singleton — for unit tests only."""
    global _singleton
    _singleton = None
```

Move `sandbox/local/list_dir.py` → `sandbox/list_dir.py` (no content change needed; just relocate). Update imports of `from deerflow.sandbox.local.list_dir import list_dir` → `from deerflow.sandbox.list_dir import list_dir` everywhere (grep first).

- [ ] **Step 4: Update `sandbox/__init__.py`**

```python
# sandbox/__init__.py
from .local_sandbox import get_sandbox, reset_sandbox_for_tests
from .sandbox import Sandbox

__all__ = ["Sandbox", "get_sandbox", "reset_sandbox_for_tests"]
```

- [ ] **Step 5: Delete obsolete files**

```bash
rm backend/packages/harness/deerflow/sandbox/sandbox_provider.py
rm backend/packages/harness/deerflow/sandbox/middleware.py
rm -rf backend/packages/harness/deerflow/sandbox/local/
```

- [ ] **Step 6: Replace all callsites of `get_sandbox_provider`**

```
cd backend && grep -rn "get_sandbox_provider" packages/ app/ tests/
```

For each: replace with `get_sandbox()`.

In `sandbox/tools.py`'s `ensure_sandbox_initialized` helper: simplify to return `get_sandbox()` (regardless of state/runtime context).

- [ ] **Step 7: Run lint + tests**

```
cd backend && make lint && uv run pytest tests/ -x -q 2>&1 | tail -20
```

Expected failures in tests using `path_mappings` (deleted): `test_local_sandbox_provider_mounts.py`, `test_sandbox_search_tools.py` (if it relies on path translation), `test_sandbox_audit_middleware.py`, `test_sandbox_orphan_reconciliation*.py`. We delete these in 4.5.

- [ ] **Step 8: Run new singleton test, verify pass**

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): collapse SandboxProvider into get_sandbox singleton"
```

### Task 4.5: Delete now-stale tests

**Files:**
- Delete: `backend/tests/test_local_sandbox_provider_mounts.py`
- Delete: `backend/tests/test_sandbox_audit_middleware.py`
- Delete: `backend/tests/test_sandbox_orphan_reconciliation.py`
- Delete: `backend/tests/test_sandbox_orphan_reconciliation_e2e.py`

- [ ] **Step 1: Delete files**

```bash
rm backend/tests/test_local_sandbox_provider_mounts.py \
   backend/tests/test_sandbox_audit_middleware.py \
   backend/tests/test_sandbox_orphan_reconciliation.py \
   backend/tests/test_sandbox_orphan_reconciliation_e2e.py
```

- [ ] **Step 2: Verify no other tests reference the deleted symbols**

```
cd backend && grep -rn "SandboxAuditMiddleware\|SandboxProvider\|reconcile_orphan" tests/
```
Expected: empty.

- [ ] **Step 3: Run tests**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | tail -10
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(sandbox): delete tests for removed provider lifecycle"
```

---

# Stage 5: Add prompt template variables (Spec Step 6 mechanism)

### Task 5.1: Extend `apply_prompt_template` to inject `{workspace_path}` / `{uploads_path}` / `{outputs_path}` / `{skills_path}`

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/agent.py` (caller)
- Test: `backend/tests/test_apply_prompt_template_path_vars.py` (new)

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_apply_prompt_template_path_vars.py
from deerflow.agents.lead_agent.prompt import apply_prompt_template


def test_template_substitutes_path_vars():
    rendered = apply_prompt_template(
        subagent_enabled=False,
        max_concurrent_subagents=3,
        agent_name="DeerFlow",
        available_skills=set(),
        workspace_path="/var/lib/deerflow/threads/abc/user-data/workspace",
        uploads_path="/var/lib/deerflow/threads/abc/user-data/uploads",
        outputs_path="/var/lib/deerflow/threads/abc/user-data/outputs",
        skills_path="/repo/skills",
    )
    assert "/var/lib/deerflow/threads/abc/user-data/workspace" in rendered
    assert "/repo/skills" in rendered
    assert "/mnt/user-data" not in rendered
    assert "/mnt/skills" not in rendered
```

- [ ] **Step 2: Run, fail (function signature lacks new kwargs and template still has `/mnt/...` literals)**

- [ ] **Step 3: Extend signature**

In `prompt.py`, modify `apply_prompt_template` to accept four new keyword-only parameters with sensible defaults (defaults are real paths derived from `Paths`):

```python
def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    *,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
    workspace_path: str | None = None,
    uploads_path: str | None = None,
    outputs_path: str | None = None,
    skills_path: str | None = None,
) -> str:
    # ... existing body ...
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        # existing vars...
        workspace_path=workspace_path or "<workspace not yet initialized>",
        uploads_path=uploads_path or "<uploads not yet initialized>",
        outputs_path=outputs_path or "<outputs not yet initialized>",
        skills_path=skills_path or "<skills not configured>",
    )
    ...
```

Update all `/mnt/user-data/{workspace,uploads,outputs}` and `/mnt/skills/...` literals in `SYSTEM_PROMPT_TEMPLATE` to use `{workspace_path}`, `{uploads_path}`, `{outputs_path}`, `{skills_path}` placeholders. **Specifically the lines noted in the brainstorming survey:**

- L217 (subagent example): `read_file("{workspace_path}/README.md")`
- L440-442 (paths block): replace `/mnt/user-data/{uploads,workspace,outputs}` with `{uploads_path}`, `{workspace_path}`, `{outputs_path}`
- L448-449, L451-452, L529: all `/mnt/user-data/...` → `{workspace_path}` / `{outputs_path}`
- L614 fallback: replace `"/mnt/skills"` with the actual skills_path computed at call time
- L677-680, L703 (ACP block): leave `/mnt/acp-workspace` literals — those refer to ACP's own container path; replace `/mnt/user-data` literals with `{workspace_path}` / `{uploads_path}` / `{outputs_path}` as appropriate

Also update `_build_subagent_section`, `_build_acp_section`, `_build_custom_mounts_section` if they format `/mnt/...` literals — they should accept the path values via parameters and format-substitute.

- [ ] **Step 4: Update `agent.py` callers of `apply_prompt_template`**

In `lead_agent/agent.py:307+` (`make_lead_agent` and any helper), pipe the values through:

```python
from deerflow.config.paths import get_paths
from deerflow.config import get_app_config

paths = get_paths()
thread_data = state.get("thread_data") or {}
skills_path = str(get_app_config().skills.get_skills_path())

prompt = apply_prompt_template(
    ...,
    workspace_path=thread_data.get("workspace_path"),
    uploads_path=thread_data.get("uploads_path"),
    outputs_path=thread_data.get("outputs_path"),
    skills_path=skills_path,
)
```

If the rendered prompt happens at agent-build time (before thread is known), use `Paths.sandbox_work_dir(thread_id)` etc. with thread_id from runtime context. Verify the existing call structure first.

- [ ] **Step 5: Run new test, verify pass**

```
cd backend && uv run pytest tests/test_apply_prompt_template_path_vars.py -v
```

- [ ] **Step 6: Run all backend tests**

Expected: `test_lead_agent_prompt.py`, `test_subagent_prompt_security.py`, `test_lead_agent_skills.py` may fail (they assert `/mnt/...` substrings). Note them; we update those tests in Task 5.6.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(prompt): inject {workspace,uploads,outputs,skills}_path template vars"
```

### Task 5.2: Rewrite subagent prompts

**Files:**
- Modify: `backend/packages/harness/deerflow/subagents/builtins/general_purpose.py`
- Modify: `backend/packages/harness/deerflow/subagents/builtins/bash_agent.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_subagent_prompt_paths.py
def test_general_purpose_no_mnt_literal():
    from deerflow.subagents.builtins.general_purpose import build_system_prompt
    rendered = build_system_prompt(
        workspace_path="/ws", uploads_path="/up", outputs_path="/out", skills_path="/sk"
    )
    assert "/mnt/user-data" not in rendered
    assert "/ws" in rendered
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Refactor each subagent's `system_prompt` from a static string to `build_system_prompt(workspace_path, uploads_path, outputs_path, skills_path) -> str`**, replacing all `/mnt/user-data/...` literals with format placeholders. Update the subagent's registry registration to pass these from runtime context.

Specific lines from survey:

- `general_purpose.py:38-42`: `/mnt/user-data/{uploads,workspace,outputs}` → `{uploads_path}`, `{workspace_path}`, `{outputs_path}`
- `bash_agent.py:38-42`: same

- [ ] **Step 4: Update `subagents/executor.py` (or registry) to thread `thread_data` through to `build_system_prompt`**

```
cd backend && grep -n "system_prompt" packages/harness/deerflow/subagents/registry.py packages/harness/deerflow/subagents/executor.py
```

- [ ] **Step 5: Run tests, pass**

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(subagents): swap /mnt literals for path template vars"
```

### Task 5.3: Rewrite uploads + memory + summarization middleware prompt strings

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`
- Modify: `backend/packages/harness/deerflow/agents/memory/updater.py`
- Modify: `backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_uploads_middleware_paths.py
def test_uploads_middleware_uses_real_path():
    from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
    state = {"thread_data": {"uploads_path": "/real/uploads"}, "uploaded_files": [{"filename": "x.csv"}]}
    runtime = ...  # construct minimal runtime
    rendered = UploadsMiddleware()._build_user_block(state, runtime)
    assert "/real/uploads" in rendered
    assert "/mnt/user-data" not in rendered
```

(Adapt the test to whatever the middleware's external surface is; if it produces a HumanMessage, assert on `.content`.)

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Surgery**

`uploads_middleware.py` — replace each `/mnt/user-data/uploads/` literal (lines 105, 140, 142, 180, 241) with `{uploads_path}/` formatted at runtime from `state["thread_data"]["uploads_path"]`.

`memory/updater.py:260` — `_UPLOAD_SENTENCE_RE` regex includes literal `/mnt/user-data/uploads/`. Two options:
1. Replace with a regex that matches the actual `uploads_path` substring (computed per-thread).
2. Drop the regex entirely if memory's job is now to keep absolute-path mentions.

Recommend (1): pass `uploads_path` into `_strip_upload_mentions_from_memory` and compile the regex inside that function with `re.escape(uploads_path)` instead of the literal.

`summarization_middleware.py:113` — drop `_skills_container_path` parameter; use `config.skills.get_skills_path()` host real path instead.

- [ ] **Step 4: Run, pass**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(prompts): purge /mnt literals from middleware prompt builders"
```

### Task 5.4: Rewrite skill SKILL.md files (10 files)

**Files:**
- Modify: 10 `skills/public/*/SKILL.md` files plus a few companions

- [ ] **Step 1: Mass replacement strategy**

For each skill, the substitutions follow these rules:
- `/mnt/user-data/workspace/` → `your workspace directory` (when used in prose) or relative `./` (when used as a path the LLM should pass to a script)
- `/mnt/user-data/uploads/` → `your uploads directory` (prose) or `<uploads_path>/` (as path; the actual path is supplied by framework prompt before the skill is read)
- `/mnt/user-data/outputs/` → `your outputs directory` (prose) or `<outputs_path>/` (as path)
- `/mnt/skills/<name>/path/to/file` → `./path/to/file` (relative to the skill's own root)
- `/mnt/skills/public/<other-skill>/SKILL.md` → "the `<other-skill>` skill" (prose reference; LLM looks it up via the skills index)

Apply these per skill. Concrete file list (from survey J16):

1. `skills/public/vercel-deploy-claimable/SKILL.md` (4 occurrences, all `/mnt/skills/user/vercel-deploy/scripts/deploy.sh`) — replace with `./scripts/deploy.sh` or repath properly
2. `skills/public/image-generation/SKILL.md` (~17 occurrences)
3. `skills/public/data-analysis/SKILL.md` (~22 occurrences across script invocations)
4. `skills/public/ppt-generation/SKILL.md` (~36 occurrences)
5. `skills/public/podcast-generation/SKILL.md` (~14)
6. `skills/public/podcast-generation/templates/tech-explainer.md` (lines 51-54)
7. `skills/public/code-documentation/SKILL.md` (~7)
8. `skills/public/newsletter-generation/SKILL.md` (1)
9. `skills/public/systematic-literature-review/SKILL.md` (~3)
10. `skills/public/systematic-literature-review/evals/evals.json` (3 — these are eval inputs; replacement should keep them as host-path examples)
11. `skills/public/academic-paper-review/SKILL.md` (1)
12. `skills/public/video-generation/SKILL.md` (~10)

**Important rule:** Do NOT use `{workspace_path}` Jinja-style placeholders in SKILL.md files — these are static documents, not templates (per spec §3.2). Use natural-language references ("your workspace") for prose; for command examples, use either `./relative/path` (when relative makes sense) or invent placeholders like `<UPLOADS_DIR>` with a one-line note "<UPLOADS_DIR> is the absolute path to your uploads directory provided in your system prompt".

- [ ] **Step 2: Process each file**

For each SKILL.md, do `view` → identify lines → `multiedit` to apply replacements. Recommend dispatching as one parallel agent per skill family (image-gen, ppt, podcast, etc.) — but in this plan, treat as a single task done sequentially.

Concrete replacement template (apply to each invocation block):

```
BEFORE:
  python /mnt/skills/public/image-generation/scripts/generate.py \
    --prompt-file /mnt/user-data/workspace/prompt-file.json \
    --output-file /mnt/user-data/outputs/generated-image.jpg

AFTER:
  python ./scripts/generate.py \
    --prompt-file <WORKSPACE_DIR>/prompt-file.json \
    --output-file <OUTPUTS_DIR>/generated-image.jpg
```

Add a one-line note at top of each SKILL.md (after frontmatter) if not already present:

> Note: `<WORKSPACE_DIR>`, `<UPLOADS_DIR>`, `<OUTPUTS_DIR>` are absolute paths; their concrete values are provided in your system prompt.

- [ ] **Step 3: Verify zero `/mnt/user-data` and zero `/mnt/skills` remain in skills**

```bash
grep -rn "/mnt/user-data\|/mnt/skills" skills/public/
```
Expected: empty.

- [ ] **Step 4: Run integration test that loads a skill (if any)**

```
cd backend && uv run pytest tests/test_skills_loader.py tests/test_skill_manage_tool.py -v
```

If they assert specific `/mnt/...` substrings, fix the test (Task 5.6).

- [ ] **Step 5: Commit**

```bash
git add skills/public/
git commit -m "docs(skills): replace /mnt/* literals with workspace/uploads/outputs placeholders"
```

### Task 5.5: Set bash_tool cwd to workspace_path

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_bash_tool_cwd.py
def test_bash_tool_uses_workspace_cwd(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_sandbox = MagicMock()
    fake_sandbox.execute_command.return_value = "ok"
    fake_runtime = MagicMock()
    fake_runtime.context = {"thread_id": "t1"}
    fake_runtime.state = {"thread_data": {"workspace_path": str(workspace)}}
    with patch("deerflow.sandbox.tools.ensure_sandbox_initialized", return_value=fake_sandbox), \
         patch("deerflow.sandbox.tools.ensure_thread_directories_exist"):
        bash_tool.invoke({"runtime": fake_runtime, "description": "test", "command": "pwd"})
    fake_sandbox.execute_command.assert_called_once_with("pwd", cwd=str(workspace))
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Modify `bash_tool` to call `sandbox.execute_command(command, cwd=thread_data.get("workspace_path"))`**

- [ ] **Step 4: Run, pass**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(bash): default bash cwd to thread workspace_path"
```

### Task 5.6: Update legacy tests asserting `/mnt/...` substrings

**Files:**
- Modify: many tests under `backend/tests/`

- [ ] **Step 1: Locate all remaining test failures**

```
cd backend && uv run pytest tests/ -x -q 2>&1 | grep -E "FAIL|ERROR" | head -30
```

- [ ] **Step 2: For each failing test, update assertions**

Target list (from survey I14):
- `test_lead_agent_prompt.py` — assert template variables present, no `/mnt/...`
- `test_lead_agent_skills.py` — same
- `test_subagent_prompt_security.py` — same
- `test_summarization_middleware.py` — same (uses `_skills_container_path`)
- `test_uploads_middleware_core_logic.py` — assert `uploads_path` value substituted
- `test_uploads_router.py` — likely about URL shape; address in Task 6.x
- `test_present_file_tool_core_logic.py` — address in Task 6.x
- `test_artifacts_router.py` — address in Task 6.x
- `test_invoke_acp_agent_tool.py` — leave `/mnt/acp-workspace` assertions intact; remove `/mnt/user-data` references
- `test_skill_manage_tool.py`, `test_skills_custom_router.py`, `test_skills_loader.py` — adapt to new SKILL.md content
- `test_view_image_middleware.py` — only update if it asserts `/mnt/...`
- `test_memory_upload_filtering.py` — adjust regex assertions
- `test_lead_agent_prompt.py` — explicit
- `test_provisioner_pvc_volumes.py` — likely irrelevant after AioSandbox removal; may be deleted
- `test_channel_file_attachments.py`, `test_channels.py`, `test_client*.py`, `test_feishu_parser.py`, `test_wechat_channel.py` — these likely use `/mnt/user-data` URLs in test fixtures; update to new short URL form once Task 6.2 lands, otherwise leave for that point

- [ ] **Step 3: Run tests until backend green excluding the URL-shape tests (those land in Stage 6)**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: align prompt/middleware tests with template-var injection"
```

---

# Stage 6: Remove path translation (Spec Step 5 mechanism)

### Task 6.1: Switch `present_file_tool` to host paths and `outputs_path` whitelist

**Files:**
- Modify: `backend/packages/harness/deerflow/tools/builtins/present_file_tool.py`
- Modify: `backend/tests/test_present_file_tool_core_logic.py`

- [ ] **Step 1: Write failing test**

```python
# Update test_present_file_tool_core_logic.py
def test_present_file_accepts_host_path(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    f = outputs / "report.pdf"
    f.write_text("data")

    runtime = make_runtime(thread_data={"outputs_path": str(outputs)}, thread_id="t1")
    result = present_file_tool.invoke({"runtime": runtime, "filepaths": [str(f)]})
    # Result is a Command updating artifacts with the host path (not virtual)
    assert str(f) in result.update["artifacts"]


def test_present_file_rejects_outside_outputs(tmp_path):
    outside = tmp_path / "elsewhere" / "x.pdf"
    outside.parent.mkdir(parents=True)
    outside.write_text("data")
    runtime = make_runtime(thread_data={"outputs_path": str(tmp_path / "outputs")}, thread_id="t1")
    result = present_file_tool.invoke({"runtime": runtime, "filepaths": [str(outside)]})
    assert "outside outputs" in str(result).lower() or "rejected" in str(result).lower()
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Rewrite `_normalize_presented_filepath`**

```python
# present_file_tool.py
def _normalize_presented_filepath(runtime, filepath: str) -> str:
    state = runtime.state if hasattr(runtime, "state") else {}
    thread_data = state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        raise ValueError("thread_data.outputs_path not initialized")

    abs_path = Path(filepath).resolve()
    outputs_root = Path(outputs_path).resolve()
    try:
        abs_path.relative_to(outputs_root)
    except ValueError:
        raise ValueError(f"path {filepath} is outside outputs directory {outputs_path}")
    return str(abs_path)
```

Drop the `OUTPUTS_VIRTUAL_PREFIX` constant and `Paths.resolve_virtual_path` calls. Update tool docstring to require absolute host paths under outputs_path.

- [ ] **Step 4: Run, pass**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(present_file): accept host paths under outputs_path"
```

### Task 6.2: Switch artifact URLs to short form with backward compat

**Files:**
- Modify: `backend/packages/harness/deerflow/uploads/manager.py`
- Modify: `backend/app/gateway/path_utils.py`
- Modify: `backend/app/gateway/routers/artifacts.py` (only if it uses `path_utils`)
- Modify: `backend/tests/test_artifacts_router.py`
- Modify: `backend/tests/test_uploads_router.py`

- [ ] **Step 1: Write failing test for new short URL form**

```python
# Update test_artifacts_router.py
def test_artifact_route_short_form(client, prepared_thread):
    """New short URL works."""
    resp = client.get(f"/api/threads/{prepared_thread}/artifacts/uploads/foo.pdf")
    assert resp.status_code == 200


def test_artifact_route_legacy_mnt_form_still_works(client, prepared_thread):
    """Legacy URL (/mnt/user-data prefix) still resolves."""
    resp = client.get(f"/api/threads/{prepared_thread}/artifacts/mnt/user-data/uploads/foo.pdf")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run, fail**

- [ ] **Step 3: Update `path_utils.resolve_thread_virtual_path`**

```python
# backend/app/gateway/path_utils.py
import logging
from pathlib import Path
from fastapi import HTTPException

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

_LEGACY_PREFIX = "mnt/user-data/"


def resolve_thread_artifact_path(thread_id: str, path: str) -> Path:
    """Resolve a thread artifact request path to a host file path.

    Accepts new short form (e.g. `uploads/foo.pdf`) and legacy form
    (`mnt/user-data/uploads/foo.pdf`).
    """
    stripped = path.lstrip("/")
    if stripped.startswith(_LEGACY_PREFIX):
        stripped = stripped[len(_LEGACY_PREFIX):]
        logger.debug("legacy artifact url shape stripped to %s", stripped)

    paths = get_paths()
    user_data = paths.sandbox_user_data_dir(thread_id).resolve()
    target = (user_data / stripped).resolve()
    try:
        target.relative_to(user_data)
    except ValueError:
        raise HTTPException(status_code=403, detail="path traversal detected")
    return target
```

Replace existing `resolve_thread_virtual_path` (rename or keep as alias for backward import).

- [ ] **Step 4: Update `artifacts.py` route to use the new helper.** Eliminate any dependence on `VIRTUAL_PATH_PREFIX`.

- [ ] **Step 5: Update `uploads/manager.py:upload_artifact_url` to emit short form**

```python
# uploads/manager.py
def upload_artifact_url(thread_id: str, filename: str) -> str:
    return f"/api/threads/{thread_id}/artifacts/uploads/{quote(filename, safe='')}"


def upload_virtual_path(filename: str) -> str:
    """[Deprecated] Returns relative path under thread user-data."""
    return f"uploads/{filename}"
```

- [ ] **Step 6: Run tests, pass**

- [ ] **Step 7: Run full backend tests; address any tests expecting the old URL shape (channel/feishu/wechat tests likely)**

```
cd backend && uv run pytest tests/ -q 2>&1 | tail -20
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(artifacts): switch to short URL with backward-compat strip"
```

### Task 6.3: Remove path translation from `LocalSandbox`

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/local_sandbox.py`

This was already done in Task 4.4 (LocalSandbox simplified — no `path_mappings`). This task verifies that downstream consumers no longer call deleted methods.

- [ ] **Step 1: Grep for remaining `_resolve_path` / `_reverse_resolve_path` references**

```
cd backend && grep -rn "_resolve_path\|_reverse_resolve_path\|path_mappings" packages/ app/ tests/
```
Expected: empty.

- [ ] **Step 2: If any matches, update them.**

- [ ] **Step 3: Commit (only if changes; otherwise mark task as N/A)**

### Task 6.4: Move `_ACP_WORKSPACE_VIRTUAL_PATH` to ACP tool

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py`
- Modify: `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py`

- [ ] **Step 1: Move the constant**

In `sandbox/tools.py`, delete `_ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"` (line ~40).

In `invoke_acp_agent_tool.py`, add at top:

```python
# Container path inside the ACP agent's own sandbox container; used in tool
# description to inform the LLM where ACP outputs land.
_ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"
```

Update any other reads of the old location.

- [ ] **Step 2: Run lint + tests**

```
cd backend && make lint && uv run pytest tests/ -x -q 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor(acp): move /mnt/acp-workspace constant into ACP tool"
```

### Task 6.5: Delete `VIRTUAL_PATH_PREFIX` and `Paths.resolve_virtual_path`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/paths.py`

- [ ] **Step 1: Verify no remaining importers**

```
cd backend && grep -rn "VIRTUAL_PATH_PREFIX\|resolve_virtual_path" packages/ app/ tests/
```

If anything outside `paths.py` and `path_utils.py` (which we updated in 6.2), update or delete.

- [ ] **Step 2: Delete the constant and method**

In `config/paths.py`:
- Delete `VIRTUAL_PATH_PREFIX = "/mnt/user-data"` at line 7
- Delete `Paths.resolve_virtual_path` method (lines ~248-281)
- Update class docstring's directory-layout box to remove `/mnt/user-data/` annotations

- [ ] **Step 3: Run tests**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(paths): delete VIRTUAL_PATH_PREFIX and resolve_virtual_path"
```

### Task 6.6: Delete `SkillsConfig.container_path` and `Skill.get_container_*`

**Files:**
- Modify: `backend/packages/harness/deerflow/config/skills_config.py`
- Modify: `backend/packages/harness/deerflow/skills/types.py`

- [ ] **Step 1: Find consumers**

```
cd backend && grep -rn "container_path\|get_container_path\|get_container_file_path\|get_skill_container_path" packages/ app/ tests/
```

- [ ] **Step 2: Update each consumer to use `skills.get_skills_path()` (host real path)**

In `agents/lead_agent/agent.py:100,103` — drop the `container_base_path` fallback; use real host path.

In `agents/middlewares/summarization_middleware.py:113` — already addressed in Task 5.3.

- [ ] **Step 3: Delete fields**

In `config/skills_config.py`:
- Delete `container_path: str = Field(default="/mnt/skills", ...)` field
- Delete `get_skill_container_path` method

In `skills/types.py`:
- Delete `Skill.get_container_path`, `Skill.get_container_file_path` methods

- [ ] **Step 4: Run lint + tests**

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(skills): delete container_path concept"
```

### Task 6.7: Frontend cosmetic literal cleanup

**Files:**
- Modify: `frontend/src/components/landing/progressive-skills-animation.tsx`

- [ ] **Step 1: View current literal context**

```
cd /data/src/deer-flow && grep -n "/mnt/skills" frontend/src/components/landing/progressive-skills-animation.tsx
```

- [ ] **Step 2: Replace with neutral display label**

Change `/mnt/skills/` → `~/skills/` (or whatever fits the animation's narrative; this is cosmetic only).

- [ ] **Step 3: Run frontend lint/typecheck**

```
cd frontend && pnpm lint && pnpm typecheck
```

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "chore(frontend): replace /mnt/skills cosmetic label"
```

---

# Stage 7: Documentation cleanup (Spec Step 8)

### Task 7.1: Update README, CONTRIBUTING, docs

**Files:**
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`
- Modify: any `docs/**/*.md` mentioning bwrap, AioSandbox, sandbox isolation, `/mnt/...`
- Modify: `.github/copilot-instructions.md` (if relevant)

- [ ] **Step 1: Grep for stale references**

```
cd /data/src/deer-flow && grep -rn "bwrap\|bubblewrap\|AioSandbox\|aio_sandbox\|/mnt/user-data\|/mnt/skills\|sandbox isolation" \
  README.md CONTRIBUTING.md docs/ .github/ 2>/dev/null
```

- [ ] **Step 2: For each hit, rewrite or delete the relevant paragraph**

Aim for: "DeerFlow runs tools directly on the host. For production isolation, run DeerFlow itself inside a container or VM."

- [ ] **Step 3: Run docs lint if any (markdownlint, etc.) — usually none**

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: remove sandbox isolation references"
```

### Task 7.2: Update Makefile / `make check`

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Search for bwrap mention**

```bash
grep -n "bwrap\|bubblewrap" Makefile
```

- [ ] **Step 2: Remove any bwrap binary check from `make check` target**

- [ ] **Step 3: Run `make check`**

```bash
make check
```
Expected: still passes.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "chore(make): drop bwrap dependency from make check"
```

---

# Stage 8: Final lint + full smoke (Spec Step 8)

### Task 8.1: Final cross-cutting lint and test sweep

- [ ] **Step 1: Backend lint and tests**

```bash
cd backend && make lint && make test
```

Both must pass cleanly.

- [ ] **Step 2: Frontend lint and typecheck**

```bash
cd frontend && pnpm lint && pnpm typecheck
```

- [ ] **Step 3: Frontend build**

```bash
cd frontend && BETTER_AUTH_SECRET=local-dev-secret pnpm build
```

- [ ] **Step 4: Final grep for residual `/mnt/user-data` and `/mnt/skills` literals across whole repo**

```bash
cd /data/src/deer-flow && grep -rn "/mnt/user-data\|/mnt/skills" \
  backend/packages backend/app frontend/src skills/ docs/ README.md CONTRIBUTING.md \
  --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=__pycache__ 2>/dev/null
```

Expected: only `/mnt/acp-workspace` mentions inside `tools/builtins/invoke_acp_agent_tool.py` (intentional ACP container path). Anything else: open a follow-up task.

- [ ] **Step 5: Commit if any cleanup**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore: final cleanup pass"
```

### Task 8.2: Generate smoke checklist

**Files:**
- Create: `docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md`

- [ ] **Step 1: Invoke generating-smoke-checklists skill**

  REQUIRED SUB-SKILL: `generating-smoke-checklists`

  Inputs:
  - Plan path: `docs/superpowers/plans/2026-05-05-remove-sandbox-isolation.md`
  - Diff window: `878be2b6..HEAD`
  - Mode: `whole-plan`

  Read all three from this plan's `## Smoke source` footer.

- [ ] **Step 2: Verify the checklist file exists and is well-formed**

  ```bash
  test -f docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md
  grep -q '^## Required (P0)' docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md
  grep -q '^### S1\.' docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md
  ```

  Expected: all three commands exit 0.

- [ ] **Step 3: Commit the checklist**

  ```bash
  git add docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md
  git commit -m "test: add smoke checklist for remove-sandbox-isolation"
  ```

### Task 8.3: Execute smoke checklist

**Files:**
- Create: `docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke-report.md`

- [ ] **Step 1: Verify the running stack the checklist assumes is healthy**

  ```bash
  curl -s http://localhost:8001/health -o /dev/null -w "gateway:%{http_code}\n"
  curl -s http://localhost:3000/ -o /dev/null -w "frontend:%{http_code}\n"
  ```

  Expected: both 200.

  If the stack is not running:
  ```bash
  make dev
  # wait for langgraph + gateway + frontend to settle
  ```

- [ ] **Step 2: Invoke executing-smoke-checklists skill**

  REQUIRED SUB-SKILL: `executing-smoke-checklists`

  Input: `docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md`

  The skill enforces evidence rules — **do not bypass it** by ticking ✓ inline here without going through it.

- [ ] **Step 3: Verify the report file exists, has a Summary, and reaches green**

  ```bash
  test -f docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke-report.md
  grep -q '^## Summary' docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke-report.md
  grep -q 'Net assessment: green' docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke-report.md
  ```

  If `Net assessment` is yellow or red:
  - **Stop the plan.** Do not commit.
  - Surface findings to the user.
  - Add new tasks to the plan that address the findings, then re-run smoke.

- [ ] **Step 4: Commit the report**

  ```bash
  git add docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke-report.md
  git commit -m "test: smoke report for remove-sandbox-isolation (green)"
  ```

---

## Smoke source

- **Plan base commit:** `878be2b6`
- **Diff window for smoke:** `878be2b6..HEAD`
- **Specs referenced (Contract surface inputs):**
  - `docs/superpowers/specs/2026-05-05-remove-sandbox-isolation-design.md`
- **Smoke mode:** `whole-plan`
