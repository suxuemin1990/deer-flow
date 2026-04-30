"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { getBackendBaseURL } from "@/core/config";
import { cancelActiveWorkflow } from "@/core/workflows/api";
import type { WorkflowParentGroup } from "@/core/workflows/types";
import { useAllWorkflows } from "@/core/workflows/use-all-workflows";

import { WorkflowRow } from "./workflow-row";

function hasActive(p: WorkflowParentGroup): boolean {
  return p.workflows.some((w) => w.status === "running");
}

function ParentGroup({ parent }: { parent: WorkflowParentGroup }) {
  const [open, setOpen] = useState(hasActive(parent));
  const queryClient = useQueryClient();

  const cancelMut = useMutation({
    mutationFn: (childThreadId: string) =>
      cancelActiveWorkflow(parent.thread_id, childThreadId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["workflows", "all"] }),
    onError: (e: Error) => toast.error(`取消失败：${e.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: async (childThreadId: string) => {
      const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
        childThreadId,
      )}`;
      const r = await fetch(url, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["workflows", "all"] }),
    onError: (e: Error) => toast.error(`删除失败：${e.message}`),
  });

  const trimmedTitle = parent.title?.trim();
  const title =
    trimmedTitle && trimmedTitle.length > 0
      ? trimmedTitle
      : `${parent.thread_id.slice(0, 8)}…`;
  const activeCount = parent.workflows.filter(
    (w) => w.status === "running",
  ).length;

  return (
    <div className="rounded-lg border">
      <Button
        variant="ghost"
        className="w-full justify-start gap-2 p-3 font-normal"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <ChevronDownIcon className="size-4" />
        ) : (
          <ChevronRightIcon className="size-4" />
        )}
        <span className="font-medium">{title}</span>
        <span className="text-muted-foreground text-xs">
          ({parent.workflows.length} 个工作流
          {activeCount > 0 ? `，${activeCount} 个进行中` : ""})
        </span>
      </Button>
      {open && (
        <ul className="border-t px-2 py-1">
          {parent.workflows.map((wf) => (
            <WorkflowRow
              key={wf.child_thread_id}
              parentThreadId={parent.thread_id}
              workflow={wf}
              onCancel={(c) => cancelMut.mutate(c)}
              onDelete={(c) => deleteMut.mutate(c)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

export function WorkflowHubTree() {
  const { data, isLoading, isError, error } = useAllWorkflows();

  if (isLoading) {
    return <div className="text-muted-foreground p-4 text-sm">加载中…</div>;
  }
  if (isError) {
    return (
      <div className="p-4 text-sm text-red-500">
        加载工作流失败：{error.message}
      </div>
    );
  }
  const parents = data?.parents ?? [];
  if (parents.length === 0) {
    return (
      <div className="text-muted-foreground p-8 text-center text-sm">
        你还没启动过任何工作流。可以在对话中让助手启动一个（例如「run demo-flow」）。
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      {parents.map((p) => (
        <ParentGroup key={p.thread_id} parent={p} />
      ))}
    </div>
  );
}
