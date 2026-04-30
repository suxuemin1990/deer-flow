"use client";

import { CheckCheckIcon, CheckIcon, XIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cancelActiveWorkflow } from "@/core/workflows/api";
import type { WorkflowEntry } from "@/core/workflows/types";
import {
  useWorkflowChat,
  type WorkflowMessage,
} from "@/core/workflows/use-workflow-chat";

import { ProgressTimeline } from "./progress-timeline";

interface Props {
  parentThreadId: string;
  workflow: WorkflowEntry;
}

function isTerminal(status: WorkflowEntry["status"]): boolean {
  return status === "done" || status === "failed" || status === "cancelled";
}

/** ✓ if server has the message; ✓✓ if any AIMessage or progress change
 *  followed it. We approximate "followed" by: index in messages array;
 *  any later message OR any progress field present beyond minimum. */
function ackFor(
  _msg: WorkflowMessage,
  index: number,
  all: WorkflowMessage[],
): "sent" | "consumed" {
  if (index < all.length - 1) return "consumed";
  return "sent";
}

export function WorkflowChatPanel({ parentThreadId, workflow }: Props) {
  const { messages, isLoading, send, isSending, progress } = useWorkflowChat(
    parentThreadId,
    workflow.child_thread_id,
  );
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // Optimistic local pending hints. Appear immediately on send; clear
  // when an equivalent server message arrives via polling. Match by
  // exact content + role==human; not perfect (rapid duplicates would
  // collapse) but the running-workflow inject path is human-paced.
  const [pendingHints, setPendingHints] = useState<
    { id: string; content: string; pushedAtCount: number }[]
  >([]);

  // Drop pending hints once the server confirms them. We compare only
  // against messages that arrived AFTER the hint was pushed, so a user
  // re-sending content that already exists in history doesn't get an
  // instantly-dropped pending bubble.
  useEffect(() => {
    if (pendingHints.length === 0) return;
    setPendingHints((prev) =>
      prev.filter((p) => {
        for (let i = p.pushedAtCount; i < messages.length; i++) {
          const m = messages[i];
          if (m?.role === "human" && m?.content === p.content) {
            return false; // drop
          }
        }
        return true; // keep
      }),
    );
  }, [messages, pendingHints.length]);

  // Autoscroll to bottom on new messages
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  const terminal = isTerminal(workflow.status);
  // Render progress fields compactly. Skip non-scalar values (lists,
  // objects) — they don't fit on a one-line header and would render as
  // "[object Object]"; users see the full structured view in the
  // terminal summary card / message panel below.
  const progressEntries = Object.entries(workflow.progress).filter(
    ([, v]) =>
      v === null ||
      v === undefined ||
      typeof v === "string" ||
      typeof v === "number" ||
      typeof v === "boolean",
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 border-b p-3">
        <span className="font-medium">{workflow.name}</span>
        <span className="text-muted-foreground text-sm">
          · {workflow.status}
          {progressEntries.length > 0 &&
            " · " +
              progressEntries
                .slice(0, 3)
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(" · ")}
        </span>
        {!terminal && (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={async () => {
              try {
                await cancelActiveWorkflow(
                  parentThreadId,
                  workflow.child_thread_id,
                );
              } catch (e) {
                toast.error(`Cancel failed: ${(e as Error).message}`);
              }
            }}
          >
            <XIcon className="size-3.5" /> Cancel
          </Button>
        )}
      </div>

      {/* Single scroll container for timeline + summary + messages.
          Guarantees header + input always visible regardless of content size. */}
      <div className="min-h-0 flex-1 overflow-auto">
        {/* Progress timeline (only when spec declares fields) */}
        {workflow.progress_timeline_fields &&
          workflow.progress_timeline_fields.length > 0 && (
            <ProgressTimeline
              values={progress}
              fields={workflow.progress_timeline_fields}
            />
          )}

        {/* Terminal summary card */}
        {terminal && (
          <div className="bg-muted/50 m-3 rounded-lg border p-3 text-sm">
            {workflow.status === "done" && workflow.report_preview && (
              <pre className="whitespace-pre-wrap font-sans">
                {workflow.report_preview}
              </pre>
            )}
            {workflow.status === "failed" && (
              <span className="text-red-600">
                {workflow.error ?? "Failed"}
              </span>
            )}
            {workflow.status === "cancelled" && (
              <span className="text-muted-foreground">
                Cancelled by user
                {workflow.error ? `: ${workflow.error}` : ""}
              </span>
            )}
          </div>
        )}

        {/* Messages */}
        <div ref={listRef} className="space-y-2 p-3">
        {isLoading && (
          <div className="text-muted-foreground text-sm">Loading…</div>
        )}
        {messages.length === 0 && !isLoading && (
          <div className="text-muted-foreground text-center text-sm">
            No messages yet.
          </div>
        )}
        {messages.map((m, i) => {
          const isUser = m.role === "human";
          const ack = isUser ? ackFor(m, i, messages) : null;
          return (
            <div
              key={m.id || `${m.role}-${i}`}
              className={`flex ${isUser ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  isUser
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                }`}
              >
                <div className="whitespace-pre-wrap">{m.content}</div>
                {ack && (
                  <div className="mt-1 flex justify-end gap-0.5 opacity-70">
                    {ack === "consumed" ? (
                      <CheckCheckIcon className="size-3" />
                    ) : (
                      <CheckIcon className="size-3" />
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {pendingHints.map((p) => (
          <div
            key={`pending-${p.id}`}
            className="flex justify-end"
            data-testid="pending-hint-bubble"
          >
            <div className="bg-primary text-primary-foreground max-w-[80%] rounded-lg px-3 py-2 text-sm opacity-60">
              <div className="whitespace-pre-wrap">{p.content}</div>
              <div className="mt-1 flex justify-end gap-0.5 opacity-70">
                <span className="text-xs">sending…</span>
              </div>
            </div>
          </div>
        ))}
        </div>
      </div>

      {/* Input */}
      <div className="border-t p-3">
        <div className="flex gap-2">
          <Textarea
            placeholder={
              terminal
                ? "Workflow has ended"
                : "Send a message to the workflow…"
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={terminal || isSending}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                const text = draft.trim();
                if (text) {
                  send(text);
                  setPendingHints((prev) => [
                    ...prev,
                    {
                      id: crypto.randomUUID(),
                      content: text,
                      pushedAtCount: messages.length,
                    },
                  ]);
                  setDraft("");
                }
              }
            }}
            className="min-h-[60px]"
          />
          <Button
            disabled={terminal || isSending || !draft.trim()}
            onClick={() => {
              const text = draft.trim();
              if (text) {
                send(text);
                setPendingHints((prev) => [
                  ...prev,
                  {
                    id: crypto.randomUUID(),
                    content: text,
                    pushedAtCount: messages.length,
                  },
                ]);
                setDraft("");
              }
            }}
          >
            Send
          </Button>
        </div>
        <div className="text-muted-foreground mt-1 text-xs">
          Enter to send · Shift+Enter for newline
        </div>
      </div>
    </div>
  );
}
