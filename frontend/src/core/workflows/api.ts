import { getBackendBaseURL } from "@/core/config";

import type { ActiveWorkflowsResponse, CancelWorkflowResponse } from "./types";

export async function fetchActiveWorkflows(
  threadId: string,
  signal?: AbortSignal,
): Promise<ActiveWorkflowsResponse> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/workflows/active`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`fetchActiveWorkflows: HTTP ${response.status}`);
  }
  return (await response.json()) as ActiveWorkflowsResponse;
}

export async function cancelActiveWorkflow(
  parentThreadId: string,
  childThreadId: string,
): Promise<CancelWorkflowResponse> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(parentThreadId)}/workflows/${encodeURIComponent(childThreadId)}/cancel`;
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) {
    throw new Error(`cancelActiveWorkflow: HTTP ${response.status}`);
  }
  return (await response.json()) as CancelWorkflowResponse;
}
