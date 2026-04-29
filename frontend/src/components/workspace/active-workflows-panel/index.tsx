"use client";

import { toast } from "sonner";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
} from "@/components/ui/sidebar";
import { useCurrentChatThreadId } from "@/core/threads/use-current-chat-thread-id";
import {
  useActiveWorkflows,
  useCancelActiveWorkflow,
} from "@/core/workflows";

import { WorkflowRow } from "./workflow-row";

export function ActiveWorkflowsPanel() {
  // Read from a module-singleton store rather than `useParams`. The chat
  // page may swap "/new" → "/<uuid>" via `history.replaceState` (to avoid
  // remounting the in-flight stream), and Next.js's `useParams` does not
  // reflect that swap — it would keep returning literal "new" and we'd
  // poll the wrong endpoint forever. The chat page publishes its real
  // thread id via `setCurrentChatThreadId`.
  const currentThreadId = useCurrentChatThreadId();

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
