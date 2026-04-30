"use client";

import { ArrowLeftIcon, BotIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BootstrapChatShell } from "@/components/workspace/agents/bootstrap-chat-shell";
import {
  AgentNameCheckError,
  checkAgentName,
  createAgent,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

type Step = "name" | "chat";

const NAME_RE = /^[A-Za-z0-9-]+$/;

function getCreateAgentErrorMessage(
  error: unknown,
  networkErrorMessage: string,
  fallbackMessage: string,
) {
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    return networkErrorMessage;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallbackMessage;
}

export default function NewAgentPage() {
  const { t } = useI18n();
  const router = useRouter();

  const [step, setStep] = useState<Step>("name");
  const [nameInput, setNameInput] = useState("");
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [agentName, setAgentName] = useState("");

  const handleConfirmName = useCallback(async () => {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setNameError("");
    setIsCheckingName(true);
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
    } catch (err) {
      if (
        err instanceof AgentNameCheckError &&
        err.reason === "backend_unreachable"
      ) {
        setNameError(t.agents.nameStepNetworkError);
      } else {
        setNameError(t.agents.nameStepCheckError);
      }
      return;
    } finally {
      setIsCheckingName(false);
    }

    setIsCreatingAgent(true);
    try {
      await createAgent({
        name: trimmed,
        description: "",
        soul: "",
      });
    } catch (err) {
      setNameError(
        getCreateAgentErrorMessage(
          err,
          t.agents.nameStepNetworkError,
          t.agents.nameStepCheckError,
        ),
      );
      return;
    } finally {
      setIsCreatingAgent(false);
    }

    setAgentName(trimmed);
    setStep("chat");
  }, [
    nameInput,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepNetworkError,
    t.agents.nameStepCheckError,
    t.agents.nameStepInvalidError,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !isIMEComposing(e)) {
      e.preventDefault();
      void handleConfirmName();
    }
  };

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
          <h1 className="text-sm font-semibold">{t.agents.createPageTitle}</h1>
        </div>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-8">
          <div className="space-y-3 text-center">
            <div className="bg-primary/10 mx-auto flex h-14 w-14 items-center justify-center rounded-full">
              <BotIcon className="text-primary h-7 w-7" />
            </div>
            <div className="space-y-1">
              <h2 className="text-xl font-semibold">
                {t.agents.nameStepTitle}
              </h2>
              <p className="text-muted-foreground text-sm">
                {t.agents.nameStepHint}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <Input
              autoFocus
              placeholder={t.agents.nameStepPlaceholder}
              value={nameInput}
              onChange={(e) => {
                setNameInput(e.target.value);
                setNameError("");
              }}
              onKeyDown={handleNameKeyDown}
              className={cn(nameError && "border-destructive")}
            />
            {nameError ? (
              <p className="text-destructive text-sm">{nameError}</p>
            ) : null}
            <Button
              className="w-full"
              onClick={() => void handleConfirmName()}
              disabled={!nameInput.trim() || isCheckingName || isCreatingAgent}
            >
              {t.agents.nameStepContinue}
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}
