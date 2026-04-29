import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { bumpThreadReloadTick } from "../threads/use-thread-reload-tick";

import { cancelActiveWorkflow, fetchActiveWorkflows } from "./api";
import type { WorkflowProgressItem } from "./types";

const POLL_INTERVAL_MS = 2_000;

export function useActiveWorkflows(threadId: string | null) {
  const queryClient = useQueryClient();
  const query = useQuery<WorkflowProgressItem[]>({
    queryKey: ["workflows", "active", threadId],
    queryFn: async ({ signal }) => {
      if (!threadId) return [];
      const res = await fetchActiveWorkflows(threadId, signal);
      return res.active;
    },
    enabled: Boolean(threadId),
    refetchInterval: threadId ? POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
    initialData: threadId ? undefined : [],
  });

  // When the active-workflow list shrinks (a workflow just finished),
  // invalidate the chat-list cache so its
  // metadata.recent_workflow_finish_at is refetched and the red-dot
  // machinery can light up without waiting for the next chat-list refresh.
  // Also bump the thread reload tick so the currently-open chat page
  // re-fetches its checkpoint state and surfaces the workflow's
  // emitted message (the LangGraph SDK's useStream does not refetch on
  // out-of-band state changes — workflow emit happens after parent idle).
  const prevCountRef = useRef<number | null>(null);
  useEffect(() => {
    const len = query.data?.length ?? null;
    if (
      prevCountRef.current !== null &&
      len !== null &&
      len < prevCountRef.current
    ) {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      if (threadId) bumpThreadReloadTick(threadId);
    }
    prevCountRef.current = len;
  }, [query.data, queryClient, threadId]);

  return query;
}

export function useCancelActiveWorkflow(parentThreadId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (childThreadId: string) => {
      if (!parentThreadId) throw new Error("parentThreadId required");
      return await cancelActiveWorkflow(parentThreadId, childThreadId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["workflows", "active", parentThreadId],
      });
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      // Backend's cancel endpoint now waits for the task's CancelledError
      // branch (which emits "[workflow:NAME] cancelled by user" to the
      // parent thread) to complete before returning. Bump the reload tick
      // so the open chat page refetches state and surfaces the message
      // immediately, instead of waiting up to ~2s for the next poll cycle.
      if (parentThreadId) bumpThreadReloadTick(parentThreadId);
    },
  });
}
