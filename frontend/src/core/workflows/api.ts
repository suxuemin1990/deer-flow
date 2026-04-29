import { getBackendBaseURL } from "@/core/config";

import type {
  AllWorkflowsResponse,
  CancelWorkflowResponse,
  PostWorkflowMessageBody,
} from "./types";

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

export async function fetchAllWorkflows(
  signal?: AbortSignal,
): Promise<AllWorkflowsResponse> {
  const url = `${getBackendBaseURL()}/api/workflows/all`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`fetchAllWorkflows: HTTP ${response.status}`);
  }
  return (await response.json()) as AllWorkflowsResponse;
}

export async function postWorkflowMessage(
  parentThreadId: string,
  childThreadId: string,
  body: PostWorkflowMessageBody,
): Promise<{ ok: true }> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    parentThreadId,
  )}/workflows/${encodeURIComponent(childThreadId)}/messages`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`postWorkflowMessage: HTTP ${response.status}`);
  }
  return (await response.json()) as { ok: true };
}
