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
}
