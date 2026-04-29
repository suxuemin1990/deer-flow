import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { cancelActiveWorkflow, fetchActiveWorkflows } from "./api";
import type { WorkflowProgressItem } from "./types";

const POLL_INTERVAL_MS = 2_000;

export function useActiveWorkflows(threadId: string | null) {
  return useQuery<WorkflowProgressItem[]>({
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
    },
  });
}
