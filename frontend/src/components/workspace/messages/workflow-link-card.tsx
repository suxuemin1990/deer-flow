"use client";

import { ListChecksIcon, ArrowRightIcon } from "lucide-react";
import Link from "next/link";

interface Props {
  childThreadId: string;
  name: string;
  url: string;
}

export function WorkflowLinkCard({ childThreadId, name, url }: Props) {
  return (
    <Link
      href={url}
      className="bg-muted/50 hover:bg-muted flex items-center gap-3 rounded-lg border p-3 transition-colors"
    >
      <ListChecksIcon className="size-5 text-blue-500" />
      <div className="flex-1">
        <div className="text-sm font-medium">View workflow: {name}</div>
        <div className="text-muted-foreground font-mono text-xs">
          {childThreadId.slice(0, 8)}…
        </div>
      </div>
      <ArrowRightIcon className="size-4 opacity-60" />
    </Link>
  );
}
