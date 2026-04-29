import { getBackendBaseURL } from "@/core/config";

export interface ThreadStateSnapshot {
  values: Record<string, unknown>;
  next: string[];
  metadata: Record<string, unknown>;
  checkpoint: { id: string | null; ts: string };
  checkpoint_id: string | null;
  parent_checkpoint_id: string | null;
  created_at: string;
  tasks: Array<{ id: string; name: string }>;
}

export async function fetchThreadState(
  threadId: string,
  signal?: AbortSignal,
): Promise<ThreadStateSnapshot> {
  const url = `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    threadId,
  )}/state`;
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(`fetchThreadState: HTTP ${r.status}`);
  return (await r.json()) as ThreadStateSnapshot;
}
