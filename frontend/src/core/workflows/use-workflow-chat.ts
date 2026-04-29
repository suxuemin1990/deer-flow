import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchThreadState,
  type ThreadStateSnapshot,
} from "../threads/api";

import { postWorkflowMessage } from "./api";

const POLL_MS = 1500;

export interface WorkflowMessage {
  id: string;
  role: "human" | "ai";
  content: string;
  ts?: string;
}

export interface AckStatus {
  /** ✓: server confirmed write. ✓✓: workflow consumed (later AIMessage or
   *  progress field changed since the user message). */
  acked: boolean;
  consumed: boolean;
}

function extractMessages(
  state: ThreadStateSnapshot | undefined,
): WorkflowMessage[] {
  const raw = state?.values?.messages;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((m: unknown) => {
      if (!m || typeof m !== "object") return null;
      const obj = m as Record<string, unknown>;
      const type = obj.type;
      const id = typeof obj.id === "string" ? obj.id : "";
      const content = typeof obj.content === "string" ? obj.content : "";
      if (type === "human") {
        return { id, role: "human", content } as WorkflowMessage;
      }
      if (type === "ai") {
        return { id, role: "ai", content } as WorkflowMessage;
      }
      return null;
    })
    .filter((m): m is WorkflowMessage => m !== null);
}

export function useWorkflowChat(
  parentThreadId: string,
  childThreadId: string,
) {
  const queryClient = useQueryClient();
  const stateQuery = useQuery<ThreadStateSnapshot>({
    queryKey: ["workflow-chat", childThreadId],
    queryFn: ({ signal }) => fetchThreadState(childThreadId, signal),
    refetchInterval: POLL_MS,
  });

  const messages = extractMessages(stateQuery.data);

  const sendMut = useMutation({
    mutationFn: (content: string) =>
      postWorkflowMessage(parentThreadId, childThreadId, { content }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["workflow-chat", childThreadId],
      }),
  });

  return {
    messages,
    progress: stateQuery.data?.values ?? {},
    isLoading: stateQuery.isLoading,
    error: stateQuery.error,
    send: sendMut.mutate,
    isSending: sendMut.isPending,
    sendError: sendMut.error,
  };
}
