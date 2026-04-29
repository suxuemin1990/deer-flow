import { useMutation, useQueryClient } from "@tanstack/react-query";

import { bumpThreadReloadTick } from "../threads/use-thread-reload-tick";

import { cancelActiveWorkflow } from "./api";

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
