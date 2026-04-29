"use client";

import { useParams } from "next/navigation";
import { toast } from "sonner";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
} from "@/components/ui/sidebar";
import {
  useActiveWorkflows,
  useCancelActiveWorkflow,
} from "@/core/workflows";

import { WorkflowRow } from "./workflow-row";

export function ActiveWorkflowsPanel() {
  const { thread_id: threadId } = useParams<{ thread_id?: string }>();
  const currentThreadId = threadId ?? null;

  const { data = [] } = useActiveWorkflows(currentThreadId);
  const { mutate: cancel, isPending: isCancelling } =
    useCancelActiveWorkflow(currentThreadId);

  if (!currentThreadId || data.length === 0) return null;

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Active workflows ({data.length})</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {data.map((item) => (
            <WorkflowRow
              key={item.thread_id}
              item={item}
              isCancelling={isCancelling}
              onCancel={(child) =>
                cancel(child, {
                  onError: (e) =>
                    toast.error(`Cancel failed: ${e.message}`),
                })
              }
            />
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
