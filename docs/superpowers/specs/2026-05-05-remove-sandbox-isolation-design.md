# Remove Sandbox Isolation — Design

Date: 2026-05-05
Status: Approved (brainstorming complete; ready for plan-writing)

## Context

DeerFlow currently carries a sandbox abstraction designed to support multiple
isolation backends — host bubblewrap (`bwrap`), a Docker/K8s-based
`AioSandboxProvider` from `community/aio_sandbox`, and a virtual-path system
(`/mnt/user-data/*`, `/mnt/skills/*`) that translates between paths the LLM
sees and real host paths. The deployment context for this project does not
need any of that isolation: the entire harness runs in environments we
control, and the cost of maintaining the abstraction (bwrap binary
dependency, Docker dependency, path-translation regex code, dual prompt
contract for skill files, virtual paths leaking into URLs) outweighs the
benefit.

We are removing the isolation modes wholesale. The user-facing `Sandbox`
abstraction stays (as a thin filesystem façade so tools have a stable
object to talk to and so we can keep cross-tool concerns like output
truncation and the file-operation lock in one place), but everything below
it collapses to a single host-direct implementation, and everything above
it (path translation, virtual prefixes appearing in prompts and URLs)
disappears.

## Goals

1. Keep the `Sandbox` abstract class as a filesystem façade for tools
   (`execute_command`, `read_file`, `write_file`, `list_dir`, `glob`,
   `grep`, `update_file`).
2. Remove the `SandboxProvider` acquire/release/get lifecycle and the
   per-thread acquire path. Replace with a single process-level
   `get_sandbox() -> Sandbox` accessor.
3. Remove bwrap (`bwrap_runner.py` + `_execute_local_bash_in_bwrap`). The
   `bash` tool runs commands in the host process space via
   `subprocess.run`, period.
4. Remove the entire `community/aio_sandbox/` module and all
   Docker/remote-sandbox-specific config fields.
5. Remove the `/mnt/user-data` / `/mnt/skills` virtual-path system. The
   LLM sees real host paths everywhere — in the system prompt, in tool
   descriptions, in tool arguments, and in tool output.
6. Remove the `sandbox.mounts` config field and `VolumeMountConfig`. Extra
   directories the LLM should see are communicated via SOUL.md / agent
   prompt, not via the sandbox config.
7. Remove the `sandbox.allow_host_bash` gate and `sandbox/security.py`.
8. Remove `SandboxMiddleware` and `SandboxState` from the LangGraph
   middleware chain and state schema.

## Non-goals

- `ThreadDataMiddleware` and `thread_data` state stay. They manage the
  per-thread workspace directory layout, which is orthogonal to
  isolation.
- The ACP agent integration keeps its own container boundary internally.
  `invoke_acp_agent_tool` continues to spawn an ACP container with a
  `/mnt/acp-workspace` bind mount — that is the contract of ACP's own
  container, not of the deerflow sandbox. The `_ACP_WORKSPACE_VIRTUAL_PATH`
  constant moves from the global sandbox tools module into the ACP tool
  itself.
- Thread workspace directory layout is unchanged
  (`<base_dir>/threads/<tid>/user-data/{workspace,uploads,outputs}`).
- We do not introduce any new sandbox provider. This is simplification,
  not extension.
- We do not refactor `Sandbox` away into a module of free functions
  (option (c) from brainstorming was rejected; option (b) — keep the
  class, drop the provider — is the chosen shape).

## Runtime shape after removal

### Module layout

```
deerflow/sandbox/
├── __init__.py           # public surface: Sandbox, get_sandbox
├── sandbox.py            # abstract base (signatures unchanged)
├── search.py             # GrepMatch, glob/grep impls (kept; isolation-orthogonal)
├── file_operation_lock.py
├── exceptions.py         # SandboxError / SandboxNotFoundError / SandboxRuntimeError
├── tools.py              # bash/ls/read/write/edit/glob/grep/present_file (no bwrap branch, no virtual paths)
├── list_dir.py           # moved up from sandbox/local/
└── local_sandbox.py      # the single concrete impl + get_sandbox() singleton
```

Deleted entirely:

- `sandbox/sandbox_provider.py`
- `sandbox/middleware.py`
- `sandbox/security.py`
- `sandbox/local/` (its meaningful contents move up to `sandbox/`)
- `community/aio_sandbox/` (every file)

### Public API (post-change)

```python
# deerflow/sandbox/__init__.py
from .sandbox import Sandbox
from .local_sandbox import get_sandbox

__all__ = ["Sandbox", "get_sandbox"]
```

```python
# deerflow/sandbox/local_sandbox.py
class LocalSandbox(Sandbox):
    def __init__(self):
        super().__init__(id="local")

    def execute_command(self, command: str, *, cwd: str | None = None) -> str:
        # Plain subprocess.run, no bwrap, no path translation.
        # cwd is set by callers (bash_tool sets it to thread workspace_path).
        ...

    def read_file(self, path: str) -> str:
        # path is a real host absolute path. No translation.
        ...
    # ...other methods analogous, all delegating to host syscalls.

_singleton: LocalSandbox | None = None

def get_sandbox() -> Sandbox:
    global _singleton
    if _singleton is None:
        _singleton = LocalSandbox()
    return _singleton
```

`Sandbox.update_file(path, content: bytes)` is kept; it has one caller
(`view_image_tool`) and is a stable signature for future binary writes.

### State / middleware

- `ThreadState.sandbox: SandboxState | None` field is removed.
- `SandboxMiddleware` is removed from the lead agent middleware chain.
- `runtime.context["sandbox_id"]` is removed. Tools that previously read
  it call `get_sandbox()` instead.
- `runtime.context["thread_id"]` and the `thread_data` state field are
  unchanged. `ThreadDataMiddleware` continues to populate
  `thread_data.{workspace,uploads,outputs}_path` with real host paths.

### Path contract for the LLM

The LLM sees real host paths everywhere. Concretely:

| Concept                | What the LLM sees (post-change)                                              |
|------------------------|-------------------------------------------------------------------------------|
| Workspace directory    | `<base_dir>/threads/<tid>/user-data/workspace`                                |
| Uploads directory      | `<base_dir>/threads/<tid>/user-data/uploads`                                  |
| Outputs directory      | `<base_dir>/threads/<tid>/user-data/outputs`                                  |
| Skills directory       | `<repo>/skills` (or whatever `config.skills.host_path` resolves to)           |

These are injected into prompts at render time via four template
variables:

- `{workspace_path}`
- `{uploads_path}`
- `{outputs_path}`
- `{skills_path}`

`{workspace_path}`, `{uploads_path}`, `{outputs_path}` come from
`thread_data` state (already present). `{skills_path}` is the global
`config.skills.host_path` (a thread-independent value, but routed through
the same injection mechanism for uniformity).

### Path contract inside skill files

Skill `SKILL.md` files do not get rewritten as Jinja templates. The
contract is:

- Inside a skill, internal references to that skill's own assets use
  **relative paths**: `./templates/foo.md`, not `/mnt/skills/<name>/...`.
- External references to skills (from the lead agent prompt, from
  subagent prompts) say "skills are at `{skills_path}/public/<name>/`"
  with `{skills_path}` filled in by the framework at prompt render time.

This keeps the skill-author contract simple (skill files are static
documents, not templates) while ensuring no `/mnt/...` literal remains.

### bash cwd convention

Tools differ in how they handle the workspace directory:

- `bash_tool` runs commands with `cwd = thread_data.workspace_path`. The
  prompt encourages the LLM to use relative paths like `./foo.py` or
  `uploads/bar.pdf` for in-workspace operations. Saves prompt tokens; the
  LLM still uses absolute paths when crossing the workspace boundary
  (e.g. reading from `{skills_path}`).
- `ls`, `read_file`, `write_file`, `glob`, `grep`, `edit` are
  single-shot stateless calls and continue to require **absolute** paths.
  This is intentional: they have no persistent cwd and absolute paths
  remove ambiguity.

### Artifact URL shape

Current shape: `/api/threads/<tid>/artifacts/mnt/user-data/uploads/<filename>`
— the `/mnt/user-data` segment appears literally in the URL.

New shape: `/api/threads/<tid>/artifacts/uploads/<filename>`.

The `mnt/user-data/` segment is stripped from URL construction
(`uploads/manager.py:get_artifact_url`). The artifact route on the
backend accepts the new shape and **also** accepts the old shape
(`/api/threads/<tid>/artifacts/mnt/user-data/...`) by stripping the
`mnt/user-data/` prefix before resolving — this keeps already-rendered
links in old chat threads working.

`VIRTUAL_PATH_PREFIX = "/mnt/user-data"` is deleted from
`config/paths.py`. `Paths.resolve_virtual_path` is deleted; callers read
`thread_data.{workspace,uploads,outputs}_path` directly.

`SkillsConfig.container_path`, `SkillsConfig.get_skill_container_path`,
`Skill.get_container_path`, `Skill.get_container_file_path` are all
deleted.

### present_file_tool

Currently uses `OUTPUTS_VIRTUAL_PREFIX = "/mnt/user-data/outputs"` as a
whitelist. After the change:

- The tool accepts host-real absolute paths.
- The whitelist is computed at runtime from `thread_data.outputs_path`.
- Frontend artifact-link rendering uses the URL returned by the tool
  (real-path-derived) and displays `basename(path)` or similar — it does
  not parse `/mnt/...` segments. Frontend changes (if any) are limited
  to display labels.

### Configuration

`SandboxConfig` shrinks to the three output-truncation fields, all of
which are isolation-orthogonal:

```python
class SandboxConfig(BaseModel):
    bash_output_max_chars: int = 20000
    read_file_output_max_chars: int = 50000
    ls_output_max_chars: int = 20000

    model_config = ConfigDict(extra="allow")
```

Removed fields: `use`, `allow_host_bash`, `image`, `port`, `replicas`,
`container_prefix`, `idle_timeout`, `mounts`, `environment`. The
`VolumeMountConfig` class is deleted.

The section name `sandbox` is kept (smallest break for existing
configs; the namespace can host future host-execution options like
timeouts or env-var allowlists).

### Backward compatibility for old configs

`SandboxConfig` already has `extra="allow"`, so unknown fields don't
fail validation. On top of that, when `config.yaml` contains a non-empty
`sandbox.use`, app startup logs a one-line warning:

```
sandbox.use is no longer supported; sandbox isolation has been removed.
The field will be ignored. Remove it from config.yaml to silence this warning.
```

No hard error, no startup block. Users discover the change without
their dev loop being interrupted.

## Implementation order

The work is sequenced so that each step ends with a green backend test
suite and a stack that still boots. Steps 5 and 6 must land together
(they are mutually-dependent — one removes the path translation, the
other removes the prompt literals that depended on it).

**Step 1 — Delete bwrap dead code (L1).**
Remove `_execute_local_bash_in_bwrap`, `BwrapMount`,
`BwrapNotInstalledError`, `execute_bwrap`, `build_bwrap_argv`, and the
entire `bwrap_runner.py`. `bash_tool` calls `sandbox.execute_command`
unconditionally. Drop bwrap-related tests.

**Step 2 — Delete the host-bash gate (L2).**
Remove `sandbox/security.py`, `SandboxConfig.allow_host_bash`, and the
gate checks in `bash_tool` and the bash subagent. Default behaviour is
"bash works."

**Step 3 — Delete AioSandbox (L3).**
Remove `community/aio_sandbox/` entirely. Remove `image`, `port`,
`replicas`, `container_prefix`, `idle_timeout`, `environment` from
`SandboxConfig`. Update `config.example.yaml`. Make `sandbox.use`
optional and add the deprecation warning described above.

**Step 4 — Slim `Sandbox` abstraction (Q6=b).**
Remove `sandbox/sandbox_provider.py`, `sandbox/middleware.py`,
`SandboxState`, the `runtime.context["sandbox_id"]` key, and the
`uses_thread_data_mounts` provider attribute. Pull the `LocalSandbox`
class up from `sandbox/local/` into `sandbox/`. Add
`get_sandbox() -> Sandbox` singleton. Replace
`get_sandbox_provider().get(...)` and `state["sandbox"]` reads with
`get_sandbox()`. Remove `SandboxMiddleware` from the lead agent
middleware chain in `agents/factory.py`. At this point the middleware
chain is shorter, but `LocalSandbox` still carries `path_mappings` —
the virtual-path system is intact and tools still translate paths.

**Step 5 + 6 — Delete virtual paths and rewrite prompts (L4 core).**

These two land in the same PR / same session because Step 5 removes the
translation code and Step 6 removes the prompt literals that depended
on it; either alone leaves the system broken.

Step 5 (mechanism):

- `LocalSandbox.__init__` drops `path_mappings`. Delete `_resolve_path`,
  `_reverse_resolve_path`, `_resolve_paths_in_command`,
  `_resolve_paths_in_content`, `_reverse_resolve_paths_in_output`.
- Delete `VIRTUAL_PATH_PREFIX` from `config/paths.py`. Delete
  `Paths.resolve_virtual_path`.
- Delete `SkillsConfig.container_path`,
  `SkillsConfig.get_skill_container_path`, `Skill.get_container_path`,
  `Skill.get_container_file_path`.
- Delete `SandboxConfig.mounts` and `VolumeMountConfig`.
- Collapse `_get_skills_container_path` / `_get_skills_host_path` in
  `sandbox/tools.py` into a single `_get_skills_path()` returning the
  host real path.
- `present_file_tool` whitelist switches from `OUTPUTS_VIRTUAL_PREFIX`
  string-prefix to `thread_data.outputs_path` containment check.
- `_ACP_WORKSPACE_VIRTUAL_PATH` moves from `sandbox/tools.py` to
  `tools/builtins/invoke_acp_agent_tool.py` as a private constant of
  that tool. Inside ACP, that string still names a real bind mount of
  the ACP container; outside ACP, the deerflow main side reads its
  output via `Paths.acp_workspace_dir(thread_id)` returning a host real
  path.

Step 6 (content):

- Extend `apply_prompt_template` (or the equivalent renderer) to
  inject `{workspace_path}`, `{uploads_path}`, `{outputs_path}`,
  `{skills_path}`. Source the first three from `thread_data` state; the
  last from `config.skills.host_path`.
- Rewrite `agents/lead_agent/prompt.py` to use those template variables
  instead of `/mnt/user-data/...` and `/mnt/skills/...` literals.
- Same rewrite for `subagents/builtins/general_purpose.py`,
  `subagents/builtins/bash_agent.py`, `agents/memory/updater.py`,
  `agents/middlewares/uploads_middleware.py`,
  `agents/middlewares/summarization_middleware.py` — every prompt
  generator that currently embeds `/mnt/...` literals.
- Rewrite the 10 `skills/public/*/SKILL.md` files: replace
  `/mnt/user-data/{workspace,uploads,outputs}` with natural-language
  references to the workspace / uploads / outputs directories; replace
  `/mnt/skills/<name>/path/to/asset` with `./path/to/asset` (relative
  to the skill's own root).
- `bash_tool` sets `cwd=thread_data.workspace_path` when calling
  `sandbox.execute_command`. The bash docstring is updated to say
  "default cwd is your workspace; use absolute paths to access uploads,
  outputs, or skills."

**Step 7 — Artifact URL shape + frontend.**

- `uploads/manager.py:get_artifact_url` (and any sibling URL
  constructors) emit `/api/threads/<tid>/artifacts/uploads/<filename>`
  (or `/outputs/...`, etc.).
- The artifact route on the backend (`backend/app/gateway/...`) accepts
  both shapes; for the legacy shape it strips the leading
  `mnt/user-data/` segment before resolving.
- `present_file_tool` accepts host real paths as input (it already
  receives them from the LLM after Step 6) and constructs the URL via
  the new helper.
- Grep the frontend for `/mnt/user-data` and `/mnt/skills`. Expected
  count: 0 or near-0. Anything found is updated to consume URLs as
  opaque strings.

**Step 8 — Docs + Makefile + smoke.**

- README, `docs/`, `CONTRIBUTING.md`, `.github/copilot-instructions.md`:
  remove or rewrite mentions of bwrap, AioSandbox, sandbox isolation,
  Docker-as-sandbox, `/mnt/user-data` virtual paths.
- `Makefile` `make check` target: drop any `bwrap` binary check (if
  present).
- Generate the smoke checklist from this spec's contract surface.
- Execute the smoke checklist against the running stack and turn the
  report green.

## Breaking changes summary

For end users:

- `config.yaml > sandbox.use` is ignored (warning at startup).
- `config.yaml > sandbox.mounts`, `sandbox.allow_host_bash`,
  `sandbox.image`, `sandbox.replicas`, `sandbox.container_prefix`,
  `sandbox.idle_timeout`, `sandbox.environment` are all ignored
  (silently, via `extra="allow"`).
- Existing thread data (`<base>/threads/*/user-data/...`) is unaffected.
- LLM-visible path strings change from `/mnt/...` to real host paths.
  This is invisible to users but may cause subtle LLM behavioural
  differences worth verifying via smoke.
- Old artifact URLs `/api/threads/<tid>/artifacts/mnt/user-data/...`
  continue to resolve thanks to the strip-prefix compatibility shim;
  new messages emit the shorter form.

For extension developers:

- `from deerflow.sandbox import get_sandbox_provider` → use
  `get_sandbox` instead.
- `SandboxProvider`, `SandboxState`, `SandboxMiddleware`,
  `VolumeMountConfig` are gone — code referencing them must be updated.
- `community/aio_sandbox` is gone — any import fails.
- `runtime.context["sandbox_id"]` is gone.

## Contract surface

Each entry: **<source path or module> → <verifiable behaviour anyone
touching the source must re-confirm>**

- `backend/packages/harness/deerflow/sandbox/local_sandbox.py:execute_command` → `bash` tool runs commands as host subprocesses (no bwrap), with `cwd` defaulted to the thread's `workspace_path`
- `backend/packages/harness/deerflow/sandbox/local_sandbox.py:read_file/write_file/list_dir/glob/grep` → these tools accept real host absolute paths and operate directly on the host filesystem; no `/mnt/*` translation occurs
- `backend/packages/harness/deerflow/sandbox/__init__.py:get_sandbox` → returns a process-level `Sandbox` singleton; `get_sandbox_provider` and `SandboxProvider` are no longer importable
- `backend/packages/harness/deerflow/agents/factory.py` (middleware chain) → the lead agent runs without `SandboxMiddleware`; `state["sandbox"]` is absent for the entire run, yet bash/ls/read/write/glob/grep all succeed
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` → the rendered system prompt contains zero occurrences of `/mnt/user-data` and zero occurrences of `/mnt/skills`; `{workspace_path}`, `{uploads_path}`, `{outputs_path}`, `{skills_path}` are substituted with real host paths
- `backend/packages/harness/deerflow/sandbox/tools.py:bash_tool` → bash commands execute with cwd set to `thread_data.workspace_path`; an LLM running `pwd` in a fresh thread sees the workspace path; relative paths like `./foo.py` resolve inside the workspace
- `backend/packages/harness/deerflow/sandbox/tools.py:present_file_tool` → accepts real host absolute paths; only files located under `thread_data.outputs_path` may be presented; paths outside that directory are rejected with a clear error
- `backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py` → ACP container still uses `/mnt/acp-workspace` internally (its own contract); the deerflow side reads ACP outputs via `Paths.acp_workspace_dir(thread_id)` real host paths
- `backend/packages/harness/deerflow/uploads/manager.py:get_artifact_url` → returned upload URLs have shape `/api/threads/<tid>/artifacts/uploads/<filename>` (no `mnt/user-data` segment)
- `backend/app/gateway/routers/...` (artifact route) → both new shape (`/api/threads/<tid>/artifacts/uploads/...`) and legacy shape (`/api/threads/<tid>/artifacts/mnt/user-data/uploads/...`) resolve to the same uploaded file
- `backend/packages/harness/deerflow/config/sandbox_config.py` → `SandboxConfig` exposes only `bash_output_max_chars`, `read_file_output_max_chars`, `ls_output_max_chars`; loading a config containing a non-empty `sandbox.use` succeeds and emits exactly one deprecation warning to logs
- `backend/packages/harness/deerflow/community/aio_sandbox/` → the package no longer exists; `from deerflow.community.aio_sandbox import ...` raises `ImportError`
- `skills/public/*/SKILL.md` → no skill markdown contains `/mnt/user-data` or `/mnt/skills` literals; intra-skill asset references use relative paths (`./templates/foo.md`)
- `frontend/src/...` (artifact link rendering) → artifact links render correctly using the new short URL shape; no frontend file contains a `/mnt/user-data` literal
