export interface CancelWorkflowResponse {
  ok: boolean;
  reason?: string;
}

export type WorkflowStatus = "running" | "done" | "failed" | "cancelled";

export const WORKFLOW_STATUS_LABEL: Record<WorkflowStatus, string> = {
  running: "运行中",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export interface WorkflowEntry {
  child_thread_id: string;
  name: string;
  status: WorkflowStatus;
  started_at: string | null;
  finished_at: string | null;
  progress: Record<string, unknown>;
  progress_timeline_fields: string[];
  report_field: string | null;
  report_preview: string | null;
  error: string | null;
}

export interface WorkflowParentGroup {
  thread_id: string;
  title: string | null;
  created_at: string;
  workflows: WorkflowEntry[];
}

export interface AllWorkflowsResponse {
  parents: WorkflowParentGroup[];
}

export interface PostWorkflowMessageBody {
  content: string;
}
