"use client";

import {
  CheckCircle2Icon,
  CircleDotIcon,
  CircleIcon,
  ExternalLinkIcon,
  TrashIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { WorkflowEntry } from "@/core/workflows/types";

const statusIcon: Record<WorkflowEntry["status"], React.ReactNode> = {
  running: <CircleDotIcon className="size-3.5 text-blue-500" />,
  done: <CheckCircle2Icon className="size-3.5 text-emerald-500" />,
  failed: <XCircleIcon className="size-3.5 text-red-500" />,
  cancelled: <CircleIcon className="text-muted-foreground size-3.5" />,
};

interface Props {
  parentThreadId: string;
  workflow: WorkflowEntry;
  onCancel: (childThreadId: string) => void;
  onDelete: (childThreadId: string) => void;
}

function summarizeProgress(workflow: WorkflowEntry): string {
  if (workflow.status === "done" && workflow.report_preview) {
    return workflow.report_preview.slice(0, 80);
  }
  if (workflow.status === "failed" && workflow.error) {
    return workflow.error.slice(0, 80);
  }
  if (workflow.status === "cancelled") {
    return "已被用户取消";
  }
  // running: render a few scalar progress fields. Lists/objects render
  // poorly inline (`[object Object]`) — let the detail page show those.
  const entries = Object.entries(workflow.progress).filter(
    ([, v]) =>
      v === null ||
      v === undefined ||
      typeof v === "string" ||
      typeof v === "number" ||
      typeof v === "boolean",
  );
  if (entries.length === 0) return "启动中…";
  return entries
    .slice(0, 3)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
}

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 60) return `${diffSec} 秒前`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`;
  return `${Math.floor(diffSec / 86400)} 天前`;
}

export function WorkflowRow({
  parentThreadId,
  workflow,
  onCancel,
  onDelete,
}: Props) {
  const ts = workflow.finished_at ?? workflow.started_at;
  return (
    <li className="group hover:bg-muted flex items-center gap-2 rounded-md px-2 py-1.5 text-sm">
      <Link
        href={`/workspace/workflows/${encodeURIComponent(workflow.child_thread_id)}`}
        className="flex flex-1 items-center gap-2 truncate"
      >
        {statusIcon[workflow.status]}
        <span className="font-medium">{workflow.name}</span>
        <span className="text-muted-foreground truncate">
          {summarizeProgress(workflow)}
        </span>
        <span className="text-muted-foreground ml-auto text-xs">
          {relativeTime(ts)}
        </span>
      </Link>
      <div className="hidden items-center gap-1 group-hover:flex">
        {workflow.status === "running" && (
          <Button
            size="icon"
            variant="ghost"
            className="size-7"
            title="取消"
            onClick={() => onCancel(workflow.child_thread_id)}
          >
            <XIcon className="size-3.5" />
          </Button>
        )}
        <Button asChild size="icon" variant="ghost" className="size-7">
          <Link
            href={`/workspace/chats/${encodeURIComponent(parentThreadId)}`}
            title="跳转到所属对话"
          >
            <ExternalLinkIcon className="size-3.5" />
          </Link>
        </Button>
        {workflow.status !== "running" && (
          <Button
            size="icon"
            variant="ghost"
            className="size-7"
            title="删除"
            onClick={() => onDelete(workflow.child_thread_id)}
          >
            <TrashIcon className="size-3.5" />
          </Button>
        )}
      </div>
    </li>
  );
}
