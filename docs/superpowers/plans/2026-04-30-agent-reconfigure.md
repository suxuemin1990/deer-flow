# Agent Reconfigure Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "重新引导" (reconfigure) entry point on each agent card that opens an existing agent's bootstrap chat — same wizard chat as creation, but skips the name step, seeds a reconfigure prompt, and overwrites the existing agent on save.

**Architecture:** Extract the bootstrap-chat phase of `new/page.tsx` into a reusable `BootstrapChatShell` component that takes `agentName` + `seedMessage` + `mode: "create" | "reconfigure"` props. New route `/workspace/agents/<name>/configure` mounts the shell with the reconfigure seed. Agent card gets a button that pushes that route. Backend `setup_agent` tool merges with existing `config.yaml` instead of overwriting blindly so non-`description`/`skills` fields (`model`, `tool_groups`) survive reconfigure.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, vitest + @testing-library/react (frontend); Python 3.12 + pytest (backend).

---

## Spec note

This plan was authored without an upstream spec (per user instruction "不需要写spec"). The design decisions captured in this plan ARE the spec: any deviation should update this document. The relevant existing context — bootstrap mode in `lead_agent/agent.py:307-371`, `setup_agent_tool.py`, `new/page.tsx` wizard flow — is referenced inline at each task.

The smoke step (Tasks 6 + 7) will fall back to the diff-only heuristic in `generating-smoke-checklists` because no spec's `## Contract surface` covers this work.

---

## Task 1: Backend — `setup_agent` merges with existing config

**Why first:** The frontend reconfigure flow is meaningless if calling it loses `model` / `tool_groups`. Land the backend safety net before any UI lights it up.

**Files:**
- Modify: `backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py:30-62`
- Modify: `backend/tests/test_setup_agent_tool.py` (append two new tests)

- [ ] **Step 1: Write a failing test for the merge behaviour**

  Append to `backend/tests/test_setup_agent_tool.py`:

  ```python
  def test_setup_agent_preserves_existing_model_and_tool_groups(tmp_path):
      """When config.yaml already exists, setup_agent must keep fields
      it doesn't manage (model, tool_groups) and only update the ones
      it does (name, description, skills)."""
      import yaml as _yaml

      runtime = _make_runtime(agent_name="reconfigure-me")
      paths = _make_paths_mock(tmp_path)
      agent_dir = paths.agent_dir("reconfigure-me")
      agent_dir.mkdir(parents=True)
      (agent_dir / "SOUL.md").write_text("old soul", encoding="utf-8")
      (agent_dir / "config.yaml").write_text(
          _yaml.dump(
              {
                  "name": "reconfigure-me",
                  "description": "old description",
                  "model": "doubao-seed-2.0",
                  "tool_groups": ["coding", "search"],
                  "skills": ["foo"],
              }
          ),
          encoding="utf-8",
      )

      with patch(
          "deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=paths
      ):
          setup_agent.invoke(
              {
                  "soul": "new soul",
                  "description": "new description",
                  "skills": ["bar"],
                  "runtime": runtime,
              }
          )

      with open(agent_dir / "config.yaml", "r", encoding="utf-8") as f:
          merged = _yaml.safe_load(f)

      assert merged["name"] == "reconfigure-me"
      assert merged["description"] == "new description"
      assert merged["skills"] == ["bar"]
      # These were NOT passed to setup_agent and must be preserved
      assert merged["model"] == "doubao-seed-2.0"
      assert merged["tool_groups"] == ["coding", "search"]
      assert (agent_dir / "SOUL.md").read_text(encoding="utf-8") == "new soul"


  def test_setup_agent_creates_minimal_config_when_no_existing_file(tmp_path):
      """First-time creation behaviour stays unchanged: no existing
      config.yaml, only the fields setup_agent wrote should appear."""
      import yaml as _yaml

      runtime = _make_runtime(agent_name="brand-new")
      paths = _make_paths_mock(tmp_path)

      with patch(
          "deerflow.tools.builtins.setup_agent_tool.get_paths", return_value=paths
      ):
          setup_agent.invoke(
              {
                  "soul": "soul",
                  "description": "desc",
                  "skills": None,
                  "runtime": runtime,
              }
          )

      with open(paths.agent_dir("brand-new") / "config.yaml", "r", encoding="utf-8") as f:
          written = _yaml.safe_load(f)

      assert written == {"name": "brand-new", "description": "desc"}
  ```

- [ ] **Step 2: Run the new tests to verify they fail**

  Run: `cd backend && uv run pytest tests/test_setup_agent_tool.py::test_setup_agent_preserves_existing_model_and_tool_groups tests/test_setup_agent_tool.py::test_setup_agent_creates_minimal_config_when_no_existing_file -v`

  Expected: both FAIL — the first because `config.yaml` is rewritten without `model`/`tool_groups`; the second should already pass but include it for parity.

- [ ] **Step 3: Implement the merge**

  Replace lines 41-51 of `backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py`:

  ```python
          if agent_name:
              # Merge with existing config to preserve fields setup_agent
              # doesn't manage (model, tool_groups, ...). Reconfigure flow
              # depends on this — a fresh write would silently drop the
              # operator-curated model / tool_groups.
              config_file = agent_dir / "config.yaml"
              existing: dict = {}
              if config_file.exists():
                  try:
                      with open(config_file, "r", encoding="utf-8") as f:
                          loaded = yaml.safe_load(f) or {}
                      if isinstance(loaded, dict):
                          existing = loaded
                  except Exception as exc:  # noqa: BLE001
                      logger.warning(
                          "[agent_creator] failed to parse existing %s: %s; "
                          "treating as empty",
                          config_file,
                          exc,
                      )

              config_data: dict = {**existing, "name": agent_name}
              if description:
                  config_data["description"] = description
              if skills is not None:
                  config_data["skills"] = skills

              with open(config_file, "w", encoding="utf-8") as f:
                  yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
  ```

- [ ] **Step 4: Run the new tests + the entire setup_agent suite**

  Run: `cd backend && uv run pytest tests/test_setup_agent_tool.py -v`

  Expected: all pre-existing tests still pass + the two new tests PASS.

- [ ] **Step 5: Run the full backend suite to catch regressions**

  Run: `cd backend && make test`

  Expected: 2255 passed (prior baseline 2253 + 2 new), 3 skipped.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py backend/tests/test_setup_agent_tool.py
  git commit -m "feat(setup_agent): merge with existing config.yaml on rewrite

  Reconfigure flow needs setup_agent to overwrite SOUL.md and
  description/skills without dropping operator-curated fields like
  model and tool_groups. Read existing config.yaml first, layer the
  tool's outputs on top, write back."
  ```

---

## Task 2: Frontend — i18n keys for reconfigure flow

**Files:**
- Modify: `frontend/src/core/i18n/locales/types.ts:118-145` (the `agents:` block)
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts:175-210`
- Modify: `frontend/src/core/i18n/locales/en-US.ts:185-220`

- [ ] **Step 1: Add keys to the `AgentTranslations` type**

  Open `frontend/src/core/i18n/locales/types.ts`. Inside the existing `agents` interface (find `createPageTitle: string;` and add immediately after the existing keys, before the closing brace of `agents`):

  ```typescript
      reconfigureCardLabel: string;
      reconfigurePageTitle: string;
      reconfigureSeedMessage: string;
      reconfigureNotFound: string;
      reconfigureBackToGallery: string;
      reconfigureCompletedTitle: string;
      reconfigureCompletedHint: string;
  ```

- [ ] **Step 2: Add Chinese values**

  Open `frontend/src/core/i18n/locales/zh-CN.ts`. Inside the `agents:` block (the one ending around line 209), add before the closing brace:

  ```typescript
      reconfigureCardLabel: "重新引导",
      reconfigurePageTitle: "重新引导：{name}",
      reconfigureSeedMessage:
        "我想继续完善智能体「{name}」的设定。请基于它当前已有的 SOUL.md 和配置，与我讨论本次想调整的方向；准备就绪后调用 setup_agent 用更新后的 SOUL 覆盖。",
      reconfigureNotFound: "找不到该智能体。可能它已被删除。",
      reconfigureBackToGallery: "返回 Gallery",
      reconfigureCompletedTitle: "智能体已更新！",
      reconfigureCompletedHint:
        "更新已生效。返回 Gallery 或直接开始一段新对话来体验调整后的设定。",
  ```

- [ ] **Step 3: Add English values**

  Open `frontend/src/core/i18n/locales/en-US.ts`. Inside the `agents:` block, add the same keys with English values:

  ```typescript
      reconfigureCardLabel: "Reconfigure",
      reconfigurePageTitle: "Reconfigure: {name}",
      reconfigureSeedMessage:
        "I'd like to keep refining the agent '{name}'. Read its current SOUL.md and config, then walk me through the changes I want to make. When we're aligned, call setup_agent with the updated SOUL to overwrite.",
      reconfigureNotFound: "Agent not found. It may have been deleted.",
      reconfigureBackToGallery: "Back to gallery",
      reconfigureCompletedTitle: "Agent updated",
      reconfigureCompletedHint:
        "The update is live. Head back to the gallery or start a new chat to try the revised settings.",
  ```

- [ ] **Step 4: Verify type and lint**

  Run: `cd frontend && pnpm typecheck && pnpm lint`

  Expected: 0 errors. (The new type members force both locale files to define matching keys; if either is missing, typecheck fails.)

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/src/core/i18n/locales
  git commit -m "i18n(agents): add reconfigure flow keys"
  ```

---

## Task 3: Frontend — Extract `BootstrapChatShell`

**Why:** `new/page.tsx` is 422 lines; the chat phase (state, useThreadStream, save handler, header dropdown, message list, prompt input, completion card) is ~200 lines that the configure page also needs verbatim. Extracting before reusing avoids divergence.

**Files:**
- Create: `frontend/src/components/workspace/agents/bootstrap-chat-shell.tsx`
- Create: `frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`
- Modify: `frontend/src/app/workspace/agents/new/page.tsx` (replace inline chat-step JSX with the shell)

- [ ] **Step 1: Write failing tests for the shell**

  Create `frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`:

  ```tsx
  // @vitest-environment jsdom
  import { render, screen, waitFor } from "@testing-library/react";
  import { describe, expect, test, vi } from "vitest";

  import { BootstrapChatShell } from "@/components/workspace/agents/bootstrap-chat-shell";

  // Mock router used by the shell
  const pushMock = vi.fn();
  vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: pushMock }),
  }));

  // Spy on useThreadStream to capture sendMessage + onToolEnd
  const sendMessageMock = vi.fn().mockResolvedValue(undefined);
  const useThreadStreamMock = vi.fn();
  vi.mock("@/core/threads/hooks", () => ({
    useThreadStream: (args: unknown) => useThreadStreamMock(args),
  }));

  // Stub agent fetch
  vi.mock("@/core/agents/api", () => ({
    getAgent: vi.fn().mockResolvedValue({
      name: "test-agent",
      description: "",
      skills: null,
    }),
  }));

  describe("BootstrapChatShell", () => {
    test("seeds the conversation with provided message on mount", async () => {
      useThreadStreamMock.mockReturnValue([
        { isLoading: false, messages: [] },
        sendMessageMock,
      ]);

      render(
        <BootstrapChatShell
          agentName="test-agent"
          seedMessage="hello {name}"
          mode="reconfigure"
        />,
      );

      await waitFor(() => {
        expect(sendMessageMock).toHaveBeenCalled();
      });
      const firstCallArgs = sendMessageMock.mock.calls[0];
      expect(firstCallArgs[1].text).toContain("test-agent");
    });

    test("does not re-seed on rerender", async () => {
      sendMessageMock.mockClear();
      useThreadStreamMock.mockReturnValue([
        { isLoading: false, messages: [] },
        sendMessageMock,
      ]);

      const { rerender } = render(
        <BootstrapChatShell
          agentName="test-agent"
          seedMessage="hello"
          mode="reconfigure"
        />,
      );
      await waitFor(() => expect(sendMessageMock).toHaveBeenCalledTimes(1));

      rerender(
        <BootstrapChatShell
          agentName="test-agent"
          seedMessage="hello"
          mode="reconfigure"
        />,
      );
      // Still exactly one seed
      expect(sendMessageMock).toHaveBeenCalledTimes(1);
    });

    test("renders header title from props", () => {
      useThreadStreamMock.mockReturnValue([
        { isLoading: false, messages: [] },
        sendMessageMock,
      ]);
      render(
        <BootstrapChatShell
          agentName="test-agent"
          seedMessage="hello"
          mode="reconfigure"
          headerTitle="重新引导：test-agent"
        />,
      );
      expect(
        screen.getByText("重新引导：test-agent"),
      ).toBeInTheDocument();
    });
  });
  ```

- [ ] **Step 2: Run the failing tests**

  Run: `cd frontend && pnpm vitest run tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`

  Expected: FAIL — file does not exist yet.

- [ ] **Step 3: Create the shell**

  Create `frontend/src/components/workspace/agents/bootstrap-chat-shell.tsx`:

  ```tsx
  "use client";

  import {
    ArrowLeftIcon,
    CheckCircleIcon,
    InfoIcon,
    MoreHorizontalIcon,
    SaveIcon,
  } from "lucide-react";
  import { useRouter } from "next/navigation";
  import { useCallback, useEffect, useMemo, useRef, useState } from "react";
  import { toast } from "sonner";

  import {
    PromptInput,
    PromptInputFooter,
    PromptInputSubmit,
    PromptInputTextarea,
  } from "@/components/ai-elements/prompt-input";
  import { Alert, AlertDescription } from "@/components/ui/alert";
  import { Button } from "@/components/ui/button";
  import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
  } from "@/components/ui/dropdown-menu";
  import { ArtifactsProvider } from "@/components/workspace/artifacts";
  import { MessageList } from "@/components/workspace/messages";
  import { ThreadContext } from "@/components/workspace/messages/context";
  import type { Agent } from "@/core/agents";
  import { getAgent } from "@/core/agents/api";
  import { useI18n } from "@/core/i18n/hooks";
  import { useThreadStream } from "@/core/threads/hooks";
  import { uuid } from "@/core/utils/uuid";
  import { cn } from "@/lib/utils";

  type SetupAgentStatus = "idle" | "requested" | "completed";
  type Mode = "create" | "reconfigure";

  const SAVE_HINT_STORAGE_KEY = "deerflow.agent-create.save-hint-seen";
  const AGENT_READ_RETRY_DELAYS_MS = [200, 500, 1_000, 2_000];

  function wait(ms: number) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function getAgentWithRetry(agentName: string) {
    for (const delay of [0, ...AGENT_READ_RETRY_DELAYS_MS]) {
      if (delay > 0) {
        await wait(delay);
      }
      try {
        return await getAgent(agentName);
      } catch {
        // retry until exhausted
      }
    }
    return null;
  }

  export interface BootstrapChatShellProps {
    /** Required so setup_agent's runtime context can route to the right dir. */
    agentName: string;
    /** First message sent on mount to seed the bootstrap LLM.
     *  May contain `{name}` which is replaced with `agentName`. */
    seedMessage: string;
    /** Drives copy on the completion card and the storage key for save-hint. */
    mode: Mode;
    /** Optional override for the header title; defaults to t.agents.createPageTitle. */
    headerTitle?: string;
  }

  export function BootstrapChatShell({
    agentName,
    seedMessage,
    mode,
    headerTitle,
  }: BootstrapChatShellProps) {
    const { t } = useI18n();
    const router = useRouter();

    const [agent, setAgent] = useState<Agent | null>(null);
    const [showSaveHint, setShowSaveHint] = useState(false);
    const [setupAgentStatus, setSetupAgentStatus] =
      useState<SetupAgentStatus>("idle");

    const threadId = useMemo(() => uuid(), []);
    const seededRef = useRef(false);

    const [thread, sendMessage] = useThreadStream({
      threadId,
      context: { mode: "flash", is_bootstrap: true },
      onFinish() {
        if (setupAgentStatus === "requested" && !agent) {
          setSetupAgentStatus("idle");
        }
      },
      onToolEnd({ name }) {
        if (name !== "setup_agent") return;
        setSetupAgentStatus("completed");
        void getAgentWithRetry(agentName).then((fetched) => {
          if (fetched) {
            setAgent(fetched);
            return;
          }
          toast.error(t.agents.agentCreatedPendingRefresh);
        });
      },
    });

    // One-shot seed
    useEffect(() => {
      if (seededRef.current) return;
      seededRef.current = true;
      const text = seedMessage.replace("{name}", agentName);
      void sendMessage(threadId, { text, files: [] }, { agent_name: agentName });
    }, [agentName, seedMessage, sendMessage, threadId]);

    useEffect(() => {
      if (typeof window === "undefined") return;
      if (window.localStorage.getItem(SAVE_HINT_STORAGE_KEY) === "1") return;
      setShowSaveHint(true);
      window.localStorage.setItem(SAVE_HINT_STORAGE_KEY, "1");
    }, []);

    const handleChatSubmit = useCallback(
      async (text: string) => {
        const trimmed = text.trim();
        if (!trimmed || thread.isLoading) return;
        await sendMessage(
          threadId,
          { text: trimmed, files: [] },
          { agent_name: agentName },
        );
      },
      [agentName, sendMessage, thread.isLoading, threadId],
    );

    const handleSaveAgent = useCallback(async () => {
      if (
        agent ||
        thread.isLoading ||
        setupAgentStatus !== "idle"
      ) {
        return;
      }

      setSetupAgentStatus("requested");
      setShowSaveHint(false);
      try {
        await sendMessage(
          threadId,
          { text: t.agents.saveCommandMessage, files: [] },
          { agent_name: agentName },
          { additionalKwargs: { hide_from_ui: true } },
        );
        toast.success(t.agents.saveRequested);
      } catch (error) {
        setSetupAgentStatus("idle");
        toast.error(error instanceof Error ? error.message : String(error));
      }
    }, [
      agent,
      agentName,
      sendMessage,
      setupAgentStatus,
      t.agents.saveCommandMessage,
      t.agents.saveRequested,
      thread.isLoading,
      threadId,
    ]);

    const completedTitle =
      mode === "reconfigure"
        ? t.agents.reconfigureCompletedTitle
        : t.agents.agentCreated;
    const completedHint =
      mode === "reconfigure"
        ? t.agents.reconfigureCompletedHint
        : null;

    return (
      <ThreadContext.Provider value={{ thread }}>
        <ArtifactsProvider>
          <div className="flex size-full flex-col">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
              <div className="flex items-center gap-3">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => router.push("/workspace/agents")}
                >
                  <ArrowLeftIcon className="h-4 w-4" />
                </Button>
                <h1 className="text-sm font-semibold">
                  {headerTitle ?? t.agents.createPageTitle}
                </h1>
              </div>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label={t.agents.more}>
                    <MoreHorizontalIcon className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => void handleSaveAgent()}
                    disabled={
                      !!agent || thread.isLoading || setupAgentStatus !== "idle"
                    }
                  >
                    <SaveIcon className="h-4 w-4" />
                    {setupAgentStatus === "requested"
                      ? t.agents.saving
                      : t.agents.save}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </header>

            <main className="flex min-h-0 flex-1 flex-col">
              {showSaveHint ? (
                <div className="px-4 pt-4">
                  <div className="mx-auto w-full max-w-(--container-width-md)">
                    <Alert>
                      <InfoIcon className="h-4 w-4" />
                      <AlertDescription>{t.agents.saveHint}</AlertDescription>
                    </Alert>
                  </div>
                </div>
              ) : null}

              <div className="flex min-h-0 flex-1 justify-center">
                <MessageList
                  className={cn("size-full", showSaveHint ? "pt-4" : "pt-10")}
                  threadId={threadId}
                  thread={thread}
                />
              </div>

              <div className="bg-background flex shrink-0 justify-center border-t px-4 py-4">
                <div className="w-full max-w-(--container-width-md)">
                  {agent ? (
                    <div className="flex flex-col items-center gap-4 rounded-2xl border py-8 text-center">
                      <CheckCircleIcon className="text-primary h-10 w-10" />
                      <p className="font-semibold">{completedTitle}</p>
                      {completedHint ? (
                        <p className="text-muted-foreground text-sm">
                          {completedHint}
                        </p>
                      ) : null}
                      <div className="flex gap-2">
                        <Button
                          onClick={() =>
                            router.push(
                              `/workspace/agents/${agentName}/chats/new`,
                            )
                          }
                        >
                          {t.agents.startChatting}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => router.push("/workspace/agents")}
                        >
                          {mode === "reconfigure"
                            ? t.agents.reconfigureBackToGallery
                            : t.agents.backToGallery}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <PromptInput
                      onSubmit={({ text }) => void handleChatSubmit(text)}
                    >
                      <PromptInputTextarea
                        autoFocus
                        placeholder={t.agents.createPageSubtitle}
                        disabled={thread.isLoading}
                      />
                      <PromptInputFooter className="justify-end">
                        <PromptInputSubmit disabled={thread.isLoading} />
                      </PromptInputFooter>
                    </PromptInput>
                  )}
                </div>
              </div>
            </main>
          </div>
        </ArtifactsProvider>
      </ThreadContext.Provider>
    );
  }
  ```

- [ ] **Step 4: Run the unit tests for the shell**

  Run: `cd frontend && pnpm vitest run tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx`

  Expected: 3 tests PASS.

- [ ] **Step 5: Refactor `new/page.tsx` to use the shell**

  Replace the chat-step return path of `frontend/src/app/workspace/agents/new/page.tsx` (the entire `return ( <ThreadContext.Provider> ... )` at lines 351-420 plus its supporting state/handlers) with a render of the shell. Concretely:

  - Drop these now-unused locals: `agent`, `setAgent`, `setupAgentStatus`, `setSetupAgentStatus`, `showSaveHint`, `setShowSaveHint`, `threadId` (the shell makes its own), `useThreadStream` call, `handleChatSubmit`, `handleSaveAgent`, the chat-step's `header` const, the entire `useEffect` for save hint, the entire `useEffect` for SAVE_HINT_STORAGE_KEY init, the `getAgentWithRetry` import, the `wait` helper, the `getCreateAgentErrorMessage` helper if no longer used (verify), the entire `<ThreadContext.Provider>...</ThreadContext.Provider>` block.
  - Keep: name-step state (`step`, `nameInput`, `nameError`, `isCheckingName`, `isCreatingAgent`, `agentName`, `handleConfirmName`, `handleNameKeyDown`, name-step JSX).
  - On chat-step: `return <BootstrapChatShell agentName={agentName} seedMessage={t.agents.nameStepBootstrapMessage} mode="create" />;`

  Final shape (chat branch only):

  ```tsx
  if (step === "chat") {
    return (
      <BootstrapChatShell
        agentName={agentName}
        seedMessage={t.agents.nameStepBootstrapMessage}
        mode="create"
      />
    );
  }

  return (
    /* ...name step JSX unchanged... */
  );
  ```

  Update imports — remove the now-unused ones, add `import { BootstrapChatShell } from "@/components/workspace/agents/bootstrap-chat-shell";`.

- [ ] **Step 6: Verify create flow still typechecks + lints**

  Run: `cd frontend && pnpm typecheck && pnpm lint`

  Expected: 0 errors, 0 warnings.

- [ ] **Step 7: Run the entire frontend unit suite**

  Run: `cd frontend && pnpm vitest run`

  Expected: all tests pass (10 files prior + 1 new = 11 files; tests count grows by 3).

- [ ] **Step 8: Commit**

  ```bash
  git add frontend/src/components/workspace/agents/bootstrap-chat-shell.tsx frontend/src/app/workspace/agents/new/page.tsx frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx
  git commit -m "refactor(agents): extract BootstrapChatShell from new/page

  Pull the chat phase (state, useThreadStream, save handler, header,
  message list, prompt input, completion card) of new/page.tsx into a
  reusable component so the upcoming reconfigure route can mount the
  same shell with a different seed and mode."
  ```

---

## Task 4: Frontend — `/workspace/agents/<name>/configure` route

**Files:**
- Create: `frontend/src/app/workspace/agents/[agent_name]/configure/page.tsx`
- Create: `frontend/tests/unit/app/workspace/agents/configure-page.test.tsx`

- [ ] **Step 1: Write failing tests**

  Create `frontend/tests/unit/app/workspace/agents/configure-page.test.tsx`:

  ```tsx
  // @vitest-environment jsdom
  import { render, screen, waitFor } from "@testing-library/react";
  import { describe, expect, test, vi } from "vitest";

  // Mocks
  const useParamsMock = vi.fn();
  vi.mock("next/navigation", () => ({
    useParams: () => useParamsMock(),
    useRouter: () => ({ push: vi.fn() }),
  }));

  const getAgentMock = vi.fn();
  vi.mock("@/core/agents/api", () => ({
    getAgent: (name: string) => getAgentMock(name),
  }));

  // Stub the shell so we don't pull in useThreadStream
  vi.mock("@/components/workspace/agents/bootstrap-chat-shell", () => ({
    BootstrapChatShell: (props: {
      agentName: string;
      seedMessage: string;
      mode: string;
    }) => (
      <div data-testid="shell">
        {props.agentName}|{props.mode}|{props.seedMessage}
      </div>
    ),
  }));

  import ConfigurePage from "@/app/workspace/agents/[agent_name]/configure/page";

  describe("ConfigurePage", () => {
    test("shows not-found state when agent missing", async () => {
      useParamsMock.mockReturnValue({ agent_name: "ghost" });
      getAgentMock.mockRejectedValue(new Error("404"));

      render(<ConfigurePage />);

      await waitFor(() => {
        expect(screen.getByText(/找不到该智能体|Agent not found/i)).toBeInTheDocument();
      });
    });

    test("mounts shell with reconfigure props when agent exists", async () => {
      useParamsMock.mockReturnValue({ agent_name: "code-writer" });
      getAgentMock.mockResolvedValue({ name: "code-writer", description: "" });

      render(<ConfigurePage />);

      await waitFor(() => {
        const shell = screen.getByTestId("shell");
        expect(shell.textContent).toContain("code-writer");
        expect(shell.textContent).toContain("reconfigure");
      });
    });
  });
  ```

- [ ] **Step 2: Run failing tests**

  Run: `cd frontend && pnpm vitest run tests/unit/app/workspace/agents/configure-page.test.tsx`

  Expected: FAIL — file does not exist.

- [ ] **Step 3: Implement the page**

  Create `frontend/src/app/workspace/agents/[agent_name]/configure/page.tsx`:

  ```tsx
  "use client";

  import { ArrowLeftIcon } from "lucide-react";
  import { useParams, useRouter } from "next/navigation";
  import { useEffect, useState } from "react";

  import { Button } from "@/components/ui/button";
  import { BootstrapChatShell } from "@/components/workspace/agents/bootstrap-chat-shell";
  import type { Agent } from "@/core/agents";
  import { getAgent } from "@/core/agents/api";
  import { useI18n } from "@/core/i18n/hooks";

  type LoadState =
    | { kind: "loading" }
    | { kind: "ready"; agent: Agent }
    | { kind: "missing" };

  export default function ConfigurePage() {
    const { t } = useI18n();
    const router = useRouter();
    const params = useParams<{ agent_name: string }>();
    const agentName = params?.agent_name ?? "";

    const [state, setState] = useState<LoadState>({ kind: "loading" });

    useEffect(() => {
      let cancelled = false;
      void (async () => {
        try {
          const agent = await getAgent(agentName);
          if (!cancelled) setState({ kind: "ready", agent });
        } catch {
          if (!cancelled) setState({ kind: "missing" });
        }
      })();
      return () => {
        cancelled = true;
      };
    }, [agentName]);

    if (state.kind === "loading") {
      return (
        <div className="text-muted-foreground p-4 text-sm">加载中…</div>
      );
    }

    if (state.kind === "missing") {
      return (
        <div className="flex h-full flex-col">
          <div className="border-b p-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push("/workspace/agents")}
            >
              <ArrowLeftIcon className="size-4" /> {t.agents.reconfigureBackToGallery}
            </Button>
          </div>
          <div className="text-muted-foreground p-8 text-center text-sm">
            {t.agents.reconfigureNotFound}
          </div>
        </div>
      );
    }

    return (
      <BootstrapChatShell
        agentName={state.agent.name}
        seedMessage={t.agents.reconfigureSeedMessage}
        mode="reconfigure"
        headerTitle={t.agents.reconfigurePageTitle.replace(
          "{name}",
          state.agent.name,
        )}
      />
    );
  }
  ```

- [ ] **Step 4: Run the new tests**

  Run: `cd frontend && pnpm vitest run tests/unit/app/workspace/agents/configure-page.test.tsx`

  Expected: 2 tests PASS.

- [ ] **Step 5: Run full unit suite**

  Run: `cd frontend && pnpm vitest run && pnpm typecheck && pnpm lint`

  Expected: all green.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/app/workspace/agents/[agent_name]/configure frontend/tests/unit/app/workspace/agents/configure-page.test.tsx
  git commit -m "feat(agents): add /configure route for re-running bootstrap

  Mounts BootstrapChatShell with the reconfigure seed and mode for an
  existing agent. Falls back to a not-found card if the agent has been
  deleted."
  ```

---

## Task 5: Frontend — Reconfigure button on agent card

**Files:**
- Modify: `frontend/src/components/workspace/agents/agent-card.tsx:107-123`
- Create: `frontend/tests/unit/components/workspace/agents/agent-card.test.tsx`

- [ ] **Step 1: Write failing test**

  Create `frontend/tests/unit/components/workspace/agents/agent-card.test.tsx`:

  ```tsx
  // @vitest-environment jsdom
  import { render, screen } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { describe, expect, test, vi } from "vitest";

  const pushMock = vi.fn();
  vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: pushMock }),
  }));
  vi.mock("@/core/agents", () => ({
    useDeleteAgent: () => ({
      mutateAsync: vi.fn(),
      isPending: false,
    }),
  }));

  import { AgentCard } from "@/components/workspace/agents/agent-card";

  const sample = {
    name: "code-writer",
    description: "writes code",
    skills: null,
    tool_groups: null,
    model: null,
  } as const;

  describe("AgentCard", () => {
    test("renders reconfigure button", () => {
      render(<AgentCard agent={sample} />);
      expect(screen.getByTitle(/重新引导|Reconfigure/i)).toBeInTheDocument();
    });

    test("clicking reconfigure routes to /configure", async () => {
      pushMock.mockClear();
      render(<AgentCard agent={sample} />);
      const btn = screen.getByTitle(/重新引导|Reconfigure/i);
      await userEvent.click(btn);
      expect(pushMock).toHaveBeenCalledWith(
        "/workspace/agents/code-writer/configure",
      );
    });
  });
  ```

- [ ] **Step 2: Run failing tests**

  Run: `cd frontend && pnpm vitest run tests/unit/components/workspace/agents/agent-card.test.tsx`

  Expected: FAIL — no reconfigure button exists.

- [ ] **Step 3: Add the button**

  Open `frontend/src/components/workspace/agents/agent-card.tsx`. Locate the `<CardFooter>` block (lines 107-123). Add a reconfigure button between the chat button and the trash button:

  Imports — add at the top with other lucide imports:

  ```typescript
  import { BotIcon, MessageSquareIcon, SettingsIcon, Trash2Icon } from "lucide-react";
  ```

  Add a handler near `handleChat`:

  ```typescript
  function handleReconfigure() {
    router.push(`/workspace/agents/${agent.name}/configure`);
  }
  ```

  Inside `<CardFooter>`, change the `<div className="flex gap-1">` block to:

  ```tsx
  <div className="flex gap-1">
    <Button
      size="icon"
      variant="ghost"
      className="h-8 w-8 shrink-0"
      onClick={handleReconfigure}
      title={t.agents.reconfigureCardLabel}
    >
      <SettingsIcon className="h-3.5 w-3.5" />
    </Button>
    <Button
      size="icon"
      variant="ghost"
      className="text-destructive hover:text-destructive h-8 w-8 shrink-0"
      onClick={() => setDeleteOpen(true)}
      title={t.agents.delete}
    >
      <Trash2Icon className="h-3.5 w-3.5" />
    </Button>
  </div>
  ```

- [ ] **Step 4: Run new + existing tests**

  Run: `cd frontend && pnpm vitest run tests/unit/components/workspace/agents`

  Expected: all PASS.

- [ ] **Step 5: Run full frontend unit suite + typecheck + lint**

  Run: `cd frontend && pnpm vitest run && pnpm typecheck && pnpm lint`

  Expected: all green.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/components/workspace/agents/agent-card.tsx frontend/tests/unit/components/workspace/agents/agent-card.test.tsx
  git commit -m "feat(agents): expose reconfigure entry on each agent card

  Adds a settings-icon button next to the chat/delete actions that
  routes to /workspace/agents/<name>/configure, opening the bootstrap
  chat for an existing agent."
  ```

---

## Task 6: Generate smoke checklist

**Files:**
- Create: `docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke.md`

- [ ] **Step 1: Invoke generating-smoke-checklists skill**

  REQUIRED SUB-SKILL: `generating-smoke-checklists`

  Inputs (read from this plan's `## Smoke source` footer):
  - Plan path: `docs/superpowers/plans/2026-04-30-agent-reconfigure.md`
  - Diff window: `57b20abf..HEAD`
  - Mode: `whole-plan`

  Note for the skill: this plan has no `## Contract surface` spec input. Apply the fallback (diff-only) heuristic and surface the gap in the checklist preamble.

- [ ] **Step 2: Verify the checklist file exists and is well-formed**

  ```bash
  test -f docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke.md
  grep -q '^## Required (P0)' docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke.md
  grep -q '^### S1\.' docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke.md
  ```

  Expected: all three exit 0.

- [ ] **Step 3: Commit the checklist**

  ```bash
  git add docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke.md
  git commit -m "test: add smoke checklist for agent reconfigure flow"
  ```

---

## Task 7: Execute smoke checklist

**Files:**
- Create: `docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke-report.md`

- [ ] **Step 1: Verify the running stack the checklist assumes is healthy**

  ```bash
  curl -s http://localhost:8001/health -o /dev/null -w "gateway:%{http_code}\n"
  curl -s http://localhost:3000/ -o /dev/null -w "frontend:%{http_code}\n"
  ```

  Expected: both 200. (If not, run `cd backend && make gateway` and `cd frontend && make dev` first.)

- [ ] **Step 2: Invoke executing-smoke-checklists skill**

  REQUIRED SUB-SKILL: `executing-smoke-checklists`

  Input: `docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke.md`

  Do not bypass the skill by ticking ✓ inline without going through it.

- [ ] **Step 3: Verify the report file exists, has a Summary, and reaches green**

  ```bash
  test -f docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke-report.md
  grep -q '^## Summary' docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke-report.md
  grep -q 'Net assessment: green' docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke-report.md
  ```

  If `Net assessment` is yellow or red:
  - **Stop the plan.** Do not commit.
  - Surface findings to the user.
  - Add new tasks addressing each finding (write failing test, fix, re-verify), then advance the diff window in the Smoke source footer and re-run Tasks 6 + 7.

- [ ] **Step 4: Commit the report**

  ```bash
  git add docs/superpowers/smoke/2026-04-30-agent-reconfigure-smoke-report.md
  git commit -m "test: smoke report for agent reconfigure flow (<green|yellow|red>)"
  ```

---

## Smoke source

- **Plan base commit:** `57b20abf`
- **Diff window for smoke:** `57b20abf..HEAD`
- **Specs referenced (Contract surface inputs):** _none_ — this plan was authored without a spec at user instruction; smoke generation will fall back to the diff-only heuristic.
- **Smoke mode:** `whole-plan`
