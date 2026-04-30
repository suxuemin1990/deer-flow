# Move Reconfigure SOUL Out of Seed Message Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass an agent's existing SOUL.md to the bootstrap LLM via runtime context (and a system-prompt addendum) instead of embedding it in the user's first message, eliminating the streaming jank and oversize user bubble caused by the 4–10 KB inline payload.

**Architecture:** Add a new whitelisted context key `existing_soul`. Frontend reconfigure flow stops embedding `{soul}` into `seedMessage` and instead passes `existing_soul` through `BootstrapChatShell` → `useThreadStream` `context`. Gateway forwards it into `RunnableConfig.configurable`. `make_lead_agent`'s `is_bootstrap` branch reads it and appends a small "## Current SOUL.md" section to the system prompt before delegating to the bootstrap skill.

**Tech Stack:** Python (FastAPI gateway, langgraph agent, pytest), TypeScript (Next.js, React, vitest).

---

## File Structure

- `backend/app/gateway/services.py` — extend `_CONTEXT_CONFIGURABLE_KEYS` to include `existing_soul`.
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py` — read `existing_soul` from `cfg`, pass to bootstrap-branch system prompt builder.
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` — `apply_prompt_template` accepts an optional `existing_soul` and renders a "## Current SOUL.md" section when bootstrap+soul are both present.
- `backend/tests/test_gateway_services.py` — assert `existing_soul` propagates from request context to RunnableConfig.
- `backend/tests/test_lead_agent_model_resolution.py` (or a new focused test) — assert bootstrap branch passes `existing_soul` to the prompt builder.
- `frontend/src/core/i18n/locales/zh-CN.ts`, `en-US.ts`, `types.ts` — change `reconfigureSeedMessage` to a short string with no `{soul}` placeholder.
- `frontend/src/components/workspace/agents/bootstrap-chat-shell.tsx` — new optional prop `existingSoul`; forwards it via `useThreadStream`'s `context` (plumbed as a new context key).
- `frontend/src/app/workspace/agents/[agent_name]/configure/page.tsx` — pass `existingSoul={state.agent.soul ?? undefined}` and stop string-substituting `{soul}`.
- `frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx` — update / add tests for context plumbing.
- `frontend/tests/unit/app/workspace/agents/configure-page.test.tsx` — update for new seed wording.

---

## Task 1: Backend whitelists `existing_soul` in run context

**Files:**
- Modify: `backend/app/gateway/services.py:192-204`
- Test: `backend/tests/test_gateway_services.py` (append)

- [ ] **Step 1: Write failing test**

In `backend/tests/test_gateway_services.py`, append:

```python
def test_existing_soul_propagates_from_context(monkeypatch):
    from app.gateway.services import _merge_request_context_into_run_config

    config: dict = {}
    _merge_request_context_into_run_config(
        config,
        {"agent_name": "x", "is_bootstrap": True, "existing_soul": "# soul"},
    )
    assert config["configurable"]["existing_soul"] == "# soul"
    assert config["context"]["existing_soul"] == "# soul"
```

- [ ] **Step 2: Run it to confirm failure**

Run: `cd backend && uv run pytest tests/test_gateway_services.py::test_existing_soul_propagates_from_context -xvs`
Expected: FAIL — `KeyError: 'existing_soul'` (key not in whitelist → not forwarded).

- [ ] **Step 3: Add `existing_soul` to whitelist**

In `backend/app/gateway/services.py`, change the `_CONTEXT_CONFIGURABLE_KEYS` set from:

```python
_CONTEXT_CONFIGURABLE_KEYS = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "agent_name",
        "is_bootstrap",
    }
)
```

to:

```python
_CONTEXT_CONFIGURABLE_KEYS = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "agent_name",
        "is_bootstrap",
        # Bootstrap-only: full text of the agent's existing SOUL.md when
        # the operator is reconfiguring an existing agent. Surfaced to the
        # bootstrap system prompt so the skill conversation has the prior
        # SOUL as context without inflating the user message.
        "existing_soul",
    }
)
```

- [ ] **Step 4: Re-run the test, expect PASS**

Run: `cd backend && uv run pytest tests/test_gateway_services.py::test_existing_soul_propagates_from_context -xvs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/services.py backend/tests/test_gateway_services.py
git commit -m "feat(gateway): whitelist existing_soul in run context"
```

---

## Task 2: `apply_prompt_template` renders Current SOUL section

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py:730` (signature) and the body that assembles the final string.
- Test: `backend/tests/test_lead_agent_prompt.py` (new file).

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_lead_agent_prompt.py`:

```python
from deerflow.agents.lead_agent.prompt import apply_prompt_template


def test_existing_soul_renders_in_bootstrap_prompt():
    prompt = apply_prompt_template(
        available_skills={"bootstrap"},
        existing_soul="# Hello SOUL\nUser is ljq.",
    )
    assert "## Current SOUL.md" in prompt
    assert "# Hello SOUL" in prompt
    assert "User is ljq." in prompt


def test_no_existing_soul_omits_section():
    prompt = apply_prompt_template(available_skills={"bootstrap"})
    assert "## Current SOUL.md" not in prompt
```

- [ ] **Step 2: Run it to confirm failure**

Run: `cd backend && uv run pytest tests/test_lead_agent_prompt.py -xvs`
Expected: FAIL — `TypeError: apply_prompt_template() got an unexpected keyword argument 'existing_soul'`.

- [ ] **Step 3: Extend signature and render the section**

In `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`, change the signature on line 730 from:

```python
def apply_prompt_template(subagent_enabled: bool = False, max_concurrent_subagents: int = 3, *, agent_name: str | None = None, available_skills: set[str] | None = None) -> str:
```

to:

```python
def apply_prompt_template(
    subagent_enabled: bool = False,
    max_concurrent_subagents: int = 3,
    *,
    agent_name: str | None = None,
    available_skills: set[str] | None = None,
    existing_soul: str | None = None,
) -> str:
```

Then, just before the final `return` of the assembled prompt string (locate by viewing the file's final assembly block — search for the return statement near the end of the function), prepend an existing-soul section. Concretely, add this near the section assembly:

```python
existing_soul_section = ""
if existing_soul and existing_soul.strip():
    existing_soul_section = (
        "\n\n## Current SOUL.md\n\n"
        "The operator is REconfiguring an existing agent. Below is its current "
        "`SOUL.md`. Treat it as the starting point and walk the user through "
        "the changes they want; when ready, call `setup_agent` to overwrite.\n\n"
        "```markdown\n"
        f"{existing_soul.strip()}\n"
        "```\n"
    )
```

Then append `existing_soul_section` to the final prompt before returning. The exact splice point depends on how the function currently composes its return value — find the `return` and concatenate `existing_soul_section` to whatever string is being returned (or include it in the f-string template if one is used).

- [ ] **Step 4: Re-run tests**

Run: `cd backend && uv run pytest tests/test_lead_agent_prompt.py -xvs`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/agents/lead_agent/prompt.py backend/tests/test_lead_agent_prompt.py
git commit -m "feat(prompt): render Current SOUL.md section when reconfiguring"
```

---

## Task 3: `make_lead_agent` forwards `existing_soul` to prompt template

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/agent.py:367-375`
- Test: `backend/tests/test_lead_agent_bootstrap_soul.py` (new)

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_lead_agent_bootstrap_soul.py`:

```python
from unittest.mock import patch

from deerflow.agents.lead_agent.agent import make_lead_agent


def test_bootstrap_branch_forwards_existing_soul():
    config = {
        "configurable": {
            "agent_name": "test-agent",
            "is_bootstrap": True,
            "existing_soul": "# Existing SOUL content",
        }
    }
    with patch(
        "deerflow.agents.lead_agent.agent.apply_prompt_template",
        return_value="STUB",
    ) as mock_apply, patch(
        "deerflow.agents.lead_agent.agent.create_agent",
        return_value=object(),
    ), patch(
        "deerflow.agents.lead_agent.agent.create_chat_model",
        return_value=object(),
    ), patch(
        "deerflow.agents.lead_agent.agent.get_available_tools",
        return_value=[],
    ), patch(
        "deerflow.agents.lead_agent.agent._build_middlewares",
        return_value=[],
    ):
        make_lead_agent(config)

    assert mock_apply.called
    call_kwargs = mock_apply.call_args.kwargs
    assert call_kwargs.get("existing_soul") == "# Existing SOUL content"
    assert "bootstrap" in call_kwargs.get("available_skills", set())
```

- [ ] **Step 2: Run it to confirm failure**

Run: `cd backend && uv run pytest tests/test_lead_agent_bootstrap_soul.py -xvs`
Expected: FAIL — assertion that `existing_soul` was passed (it isn't yet).

- [ ] **Step 3: Wire it through**

In `backend/packages/harness/deerflow/agents/lead_agent/agent.py`, in the `is_bootstrap` branch, change:

```python
    if is_bootstrap:
        # Special bootstrap agent with minimal prompt for initial custom agent creation flow
        return create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
            tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled) + [setup_agent],
            middleware=_build_middlewares(config, model_name=model_name),
            system_prompt=apply_prompt_template(subagent_enabled=subagent_enabled, max_concurrent_subagents=max_concurrent_subagents, available_skills=set(["bootstrap"])),
            state_schema=ThreadState,
        )
```

to:

```python
    if is_bootstrap:
        existing_soul = cfg.get("existing_soul")
        # Special bootstrap agent with minimal prompt for initial custom agent creation flow
        return create_agent(
            model=create_chat_model(name=model_name, thinking_enabled=thinking_enabled),
            tools=get_available_tools(model_name=model_name, subagent_enabled=subagent_enabled) + [setup_agent],
            middleware=_build_middlewares(config, model_name=model_name),
            system_prompt=apply_prompt_template(
                subagent_enabled=subagent_enabled,
                max_concurrent_subagents=max_concurrent_subagents,
                available_skills=set(["bootstrap"]),
                existing_soul=existing_soul,
            ),
            state_schema=ThreadState,
        )
```

- [ ] **Step 4: Re-run test**

Run: `cd backend && uv run pytest tests/test_lead_agent_bootstrap_soul.py -xvs`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite to catch regressions**

Run: `cd backend && make test`
Expected: all 277+ tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/packages/harness/deerflow/agents/lead_agent/agent.py backend/tests/test_lead_agent_bootstrap_soul.py
git commit -m "feat(agent): forward existing_soul to bootstrap prompt"
```

---

## Task 4: Frontend i18n — shrink `reconfigureSeedMessage`

**Files:**
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts:212-213`
- Modify: `frontend/src/core/i18n/locales/en-US.ts:223-225`
- Modify: `frontend/src/core/i18n/locales/types.ts:156-157` (no schema change needed; just keep both keys)

- [ ] **Step 1: Replace the templated `reconfigureSeedMessage` with a short literal**

In `zh-CN.ts`, change:

```ts
    reconfigureSeedMessage:
      "我想继续完善智能体「{name}」的设定。下面是它当前的 SOUL.md，请以此为起点和我讨论本次想调整的方向；准备就绪后调用 setup_agent 用更新后的 SOUL 整体覆盖（保留原有结构、用英文输出）。\n\n```markdown\n{soul}\n```",
    reconfigureSeedMessageNoSoul:
      "我想继续完善智能体「{name}」的设定，但它当前还没有 SOUL.md。请像首次引导那样和我对话，准备就绪后调用 setup_agent 创建初版 SOUL（英文输出）。",
```

to:

```ts
    reconfigureSeedMessage:
      "我想继续完善智能体「{name}」的设定。当前的 SOUL.md 已作为系统上下文给你，请以此为起点和我讨论本次想调整的方向；准备就绪后调用 setup_agent 用更新后的 SOUL 整体覆盖（保留原有结构、用英文输出）。",
    reconfigureSeedMessageNoSoul:
      "我想继续完善智能体「{name}」的设定，但它当前还没有 SOUL.md。请像首次引导那样和我对话，准备就绪后调用 setup_agent 创建初版 SOUL（英文输出）。",
```

In `en-US.ts`, change:

```ts
    reconfigureSeedMessage:
      "I'd like to keep refining the agent '{name}'. Below is its current SOUL.md — use it as the starting point and walk me through the changes I want to make. When we're aligned, call setup_agent with the updated SOUL to overwrite (keep the same structure, English output).\n\n```markdown\n{soul}\n```",
```

to:

```ts
    reconfigureSeedMessage:
      "I'd like to keep refining the agent '{name}'. Its current SOUL.md is already loaded as system context — use that as the starting point and walk me through the changes I want to make. When we're aligned, call setup_agent with the updated SOUL to overwrite (keep the same structure, English output).",
```

- [ ] **Step 2: Verify type-check still clean**

Run: `cd frontend && pnpm typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/i18n/locales/zh-CN.ts frontend/src/core/i18n/locales/en-US.ts
git commit -m "i18n(agents): drop {soul} placeholder from reconfigure seed"
```

---

## Task 5: Frontend `BootstrapChatShell` plumbs `existingSoul` into context

**Files:**
- Modify: `frontend/src/components/workspace/agents/bootstrap-chat-shell.tsx`
- Test: `frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`

- [ ] **Step 1: Write failing test**

In `bootstrap-chat-shell.test.tsx`, add a new test inside the existing `describe`:

```ts
test("forwards existingSoul into thread stream context", () => {
  useThreadStreamMock.mockReturnValue([
    { isLoading: false, messages: [] },
    sendMessageMock,
  ]);

  render(
    <BootstrapChatShell
      agentName="x-agent"
      seedMessage="seed"
      mode="reconfigure"
      existingSoul="# the soul"
    />,
  );

  const args = useThreadStreamMock.mock.calls[0]![0] as {
    context: Record<string, unknown>;
  };
  expect(args.context.is_bootstrap).toBe(true);
  expect(args.context.existing_soul).toBe("# the soul");
});

test("omits existing_soul when prop is absent", () => {
  useThreadStreamMock.mockReturnValue([
    { isLoading: false, messages: [] },
    sendMessageMock,
  ]);

  render(
    <BootstrapChatShell agentName="x-agent" seedMessage="seed" mode="create" />,
  );

  const args = useThreadStreamMock.mock.calls[0]![0] as {
    context: Record<string, unknown>;
  };
  expect("existing_soul" in args.context).toBe(false);
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd frontend && pnpm vitest run tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`
Expected: 2 new tests FAIL (`existingSoul` prop / `existing_soul` context not present).

- [ ] **Step 3: Add `existingSoul` prop and forward it**

In `bootstrap-chat-shell.tsx`:

(a) Extend the props interface — change:

```ts
export interface BootstrapChatShellProps {
  agentName: string;
  seedMessage: string;
  mode: Mode;
  headerTitle?: string;
}
```

to:

```ts
export interface BootstrapChatShellProps {
  agentName: string;
  seedMessage: string;
  mode: Mode;
  headerTitle?: string;
  /** When set, forwarded to the bootstrap LLM via runtime context as
   *  `existing_soul`. Used for the reconfigure flow so the model has
   *  the prior SOUL.md without inflating the user message. */
  existingSoul?: string;
}
```

(b) Destructure the new prop:

```ts
export function BootstrapChatShell({
  agentName,
  seedMessage,
  mode,
  headerTitle,
  existingSoul,
}: BootstrapChatShellProps) {
```

(c) Build the context object dynamically — change:

```ts
  const [thread, sendMessage] = useThreadStream({
    threadId,
    context: { mode: "flash", is_bootstrap: true },
```

to:

```ts
  const streamContext = useMemo(() => {
    const ctx: Record<string, unknown> = { mode: "flash", is_bootstrap: true };
    if (existingSoul && existingSoul.trim()) {
      ctx.existing_soul = existingSoul;
    }
    return ctx;
  }, [existingSoul]);

  const [thread, sendMessage] = useThreadStream({
    threadId,
    context: streamContext,
```

- [ ] **Step 4: Re-run tests, expect green**

Run: `cd frontend && pnpm vitest run tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/agents/bootstrap-chat-shell.tsx frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx
git commit -m "feat(agents): forward existingSoul into bootstrap context"
```

---

## Task 6: Configure page passes `existingSoul`, drops `{soul}` substitution

**Files:**
- Modify: `frontend/src/app/workspace/agents/[agent_name]/configure/page.tsx`
- Test: `frontend/tests/unit/app/workspace/agents/configure-page.test.tsx`

- [ ] **Step 1: Update / add test**

In `configure-page.test.tsx`, update the "ready" path test (or add a new one) to assert the page passes `existingSoul` and uses the short seed:

```ts
test("ready path passes existingSoul prop and short seed message", async () => {
  const getAgentMock = vi.fn().mockResolvedValue({
    name: "code-writer",
    description: "",
    model: null,
    tool_groups: null,
    skills: null,
    soul: "# stored soul",
  });
  vi.mocked(getAgent).mockImplementation(getAgentMock);
  // … render and wait for ready …
  // Check the BootstrapChatShell mock received existingSoul: "# stored soul"
  // and a seedMessage that does NOT contain "```markdown".
});
```

(Adjust to match the existing test file's mocking style — the file already mocks `BootstrapChatShell` to capture props.)

- [ ] **Step 2: Run failing test**

Run: `cd frontend && pnpm vitest run tests/unit/app/workspace/agents/configure-page.test.tsx`
Expected: new assertion FAILS (page still embeds `{soul}`).

- [ ] **Step 3: Update the page**

Change:

```tsx
  return (
    <BootstrapChatShell
      agentName={state.agent.name}
      seedMessage={
        state.agent.soul?.trim()
          ? t.agents.reconfigureSeedMessage.replace(
              "{soul}",
              state.agent.soul.trim(),
            )
          : t.agents.reconfigureSeedMessageNoSoul
      }
      mode="reconfigure"
      headerTitle={t.agents.reconfigurePageTitle.replace(
        "{name}",
        state.agent.name,
      )}
    />
  );
```

to:

```tsx
  const hasSoul = !!state.agent.soul?.trim();

  return (
    <BootstrapChatShell
      agentName={state.agent.name}
      seedMessage={
        hasSoul
          ? t.agents.reconfigureSeedMessage.replace(
              "{name}",
              state.agent.name,
            )
          : t.agents.reconfigureSeedMessageNoSoul.replace(
              "{name}",
              state.agent.name,
            )
      }
      mode="reconfigure"
      headerTitle={t.agents.reconfigurePageTitle.replace(
        "{name}",
        state.agent.name,
      )}
      existingSoul={hasSoul ? state.agent.soul!.trim() : undefined}
    />
  );
```

(Note: `BootstrapChatShell`'s seed-replace logic only handles `{name}` — it never substituted `{soul}`. Substitution happened at the page level. Now both branches do their own `{name}` replace and the SOUL flows through `existingSoul`.)

- [ ] **Step 4: Run all relevant frontend tests**

Run:
```bash
cd frontend && pnpm vitest run \
  tests/unit/app/workspace/agents/configure-page.test.tsx \
  tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx \
  tests/unit/components/workspace/agents/agent-card.test.tsx
```
Expected: all PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `cd frontend && pnpm lint && pnpm typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/workspace/agents/\[agent_name\]/configure/page.tsx frontend/tests/unit/app/workspace/agents/configure-page.test.tsx
git commit -m "feat(agents): pass existing SOUL via context, not user message"
```

---

## Task 7: Generate smoke checklist

**Files:**
- Create: `docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke.md`

- [ ] **Step 1: Invoke generating-smoke-checklists skill**

  REQUIRED SUB-SKILL: `generating-smoke-checklists`

  Inputs:
  - Plan path: `docs/superpowers/plans/2026-04-30-bootstrap-soul-via-context.md`
  - Diff window: `<plan-base>..HEAD` (whole-plan)
  - Mode: `whole-plan`

  Read base from this plan's `## Smoke source` footer.

- [ ] **Step 2: Verify the checklist file exists and is well-formed**

```bash
test -f docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke.md
grep -q '^## Required (P0)' docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke.md
grep -q '^### S1\.' docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke.md
```

Expected: all three commands exit 0.

- [ ] **Step 3: Commit the checklist**

```bash
git add docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke.md
git commit -m "test: add smoke checklist for bootstrap SOUL via context"
```

---

## Task 8: Execute smoke checklist

**Files:**
- Create: `docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke-report.md`

- [ ] **Step 1: Verify the running stack is healthy**

```bash
curl -s http://localhost:8001/health -o /dev/null -w "gateway:%{http_code}\n"
curl -s http://localhost:3000/ -o /dev/null -w "frontend:%{http_code}\n"
```

Expected: both 200.

- [ ] **Step 2: Invoke executing-smoke-checklists skill**

  REQUIRED SUB-SKILL: `executing-smoke-checklists`

  Input: `docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke.md`

  Specifically validate:
  - **S-perf**: Open `/workspace/agents/<existing-agent>/configure`, send a short prompt, observe that (a) no `{soul}` block is visible in the user bubble, (b) the model still references the existing SOUL ("the previous identity is X…"), (c) streaming output appears smoothly without multi-second gaps.
  - **S-no-soul**: Manually delete `SOUL.md` for a test agent (or pick one without one), open `/configure`, confirm the no-soul seed message appears and bootstrap runs from scratch.
  - **S-create**: New-agent flow at `/workspace/agents/new` still works (no `existing_soul` sent, no system-prompt regression).

- [ ] **Step 3: Verify the report file reaches green**

```bash
test -f docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke-report.md
grep -q '^## Summary' docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke-report.md
grep -q 'Net assessment: green' docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke-report.md
```

If yellow or red: **stop**, surface findings, append remediation tasks to this plan, re-run smoke.

- [ ] **Step 4: Commit the report**

```bash
git add docs/superpowers/smoke/2026-04-30-bootstrap-soul-via-context-smoke-report.md
git commit -m "test: smoke report for bootstrap SOUL via context (green)"
```

---

## Smoke source

- **Plan base commit:** `a18c99905767b310561fc82b98062126037d6ac6`
- **Diff window for smoke:** `a18c9990..HEAD`
- **Specs referenced (Contract surface inputs):**
  - (No formal spec — this is a small targeted fix on top of the agent-reconfigure plan at `docs/superpowers/plans/2026-04-30-agent-reconfigure.md`)
- **Smoke mode:** `whole-plan`
