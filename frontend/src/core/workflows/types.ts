export interface WorkflowProgressItem {
  thread_id: string;
  name: string;
  started_at: string | null;
  is_done: boolean;
  _error: string | null;
  progress: Record<string, unknown>;
}

export interface ActiveWorkflowsResponse {
  active: WorkflowProgressItem[];
}

export interface CancelWorkflowResponse {
  ok: boolean;
  reason?: string;
}
