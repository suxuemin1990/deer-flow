"use client";

import { ChevronLeftIcon } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import type { WorkflowEntry } from "@/core/workflows/types";
import { useAllWorkflows } from "@/core/workflows/use-all-workflows";

import { WorkflowChatPanel } from "./_components/workflow-chat-panel";

export default function WorkflowDetailPage() {
  const params = useParams<{ child_thread_id: string }>();
  const childTid = params?.child_thread_id ?? "";
  const { data, isLoading } = useAllWorkflows();

  // Locate the workflow + its parent across the hub tree
  let parentThreadId: string | null = null;
  let workflow: WorkflowEntry | null = null;
  for (const p of data?.parents ?? []) {
    const found = p.workflows.find((w) => w.child_thread_id === childTid);
    if (found) {
      parentThreadId = p.thread_id;
      workflow = found;
      break;
    }
  }

  if (isLoading) {
    return (
      <div className="text-muted-foreground p-4 text-sm">Loading…</div>
    );
  }

  if (!workflow || !parentThreadId) {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b p-3">
          <Button asChild variant="ghost" size="sm">
            <Link href="/workspace/workflows">
              <ChevronLeftIcon className="size-4" /> Back to workflows
            </Link>
          </Button>
        </div>
        <div className="text-muted-foreground p-8 text-center text-sm">
          Workflow not found.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-3">
        <Button asChild variant="ghost" size="sm">
          <Link href="/workspace/workflows">
            <ChevronLeftIcon className="size-4" /> Back to workflows
          </Link>
        </Button>
      </div>
      <div className="flex-1 overflow-hidden">
        <WorkflowChatPanel
          parentThreadId={parentThreadId}
          workflow={workflow}
        />
      </div>
    </div>
  );
}
