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
    onSetupAgentComplete() {
      // setup_agent succeeded — written via onUpdateEvent's Command payload.
      // The gateway does not emit `events` stream mode, so `on_tool_end`
      // never reaches us; this state-update sniff is the only reliable
      // signal that the tool finished.
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
    if (agent || thread.isLoading || setupAgentStatus !== "idle") {
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
    mode === "reconfigure" ? t.agents.reconfigureCompletedHint : null;

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
