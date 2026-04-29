"use client";

import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SidebarMenuItem } from "@/components/ui/sidebar";
import type { WorkflowProgressItem } from "@/core/workflows";

import { ProgressLine } from "./progress-line";

interface Props {
  item: WorkflowProgressItem;
  onCancel: (childThreadId: string) => void;
  isCancelling?: boolean;
}

export function WorkflowRow({ item, onCancel, isCancelling }: Props) {
  return (
    <SidebarMenuItem className="flex flex-col gap-1 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm">{item.name}</span>
        <Button
          size="icon"
          variant="ghost"
          className="h-5 w-5 shrink-0"
          aria-label={`Cancel ${item.name}`}
          disabled={isCancelling}
          onClick={() => onCancel(item.thread_id)}
        >
          <XIcon className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ProgressLine progress={item.progress} />
    </SidebarMenuItem>
  );
}
