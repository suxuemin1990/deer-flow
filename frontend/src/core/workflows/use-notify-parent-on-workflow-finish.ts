/**
 * useNotifyParentOnWorkflowFinish
 *
 * When a child workflow finishes in the background, its
 * `[workflow:NAME] done\n\n{report}` AIMessage is appended to the parent
 * thread's checkpoint via `emit_to_parent_thread` — but the LangGraph SDK's
 * `useStream` only refetches state on its own run's SSE events. The parent
 * has no run open at finish time, so the new message lives on disk
 * unnoticed until the user reloads or types something.
 *
 * This hook closes that loop entirely client-side: it tracks which child
 * workflows under `parentThreadId` were running on the previous render,
 * detects transitions to terminal (done/failed/cancelled) or disappearance,
 * and bumps the existing thread reload-tick — the same mechanism the
 * cancel mutation uses (proven path). The tick triggers a one-shot
 * `getState()` refetch in `useThreadStream`, which appends the new
 * messages as `tailMessages`.
 *
 * Caller is expected to feed the entries from the existing 3 s
 * `useAllWorkflows` poll, so this hook adds zero new HTTP traffic.
 */
import { useEffect, useRef } from "react";

import { bumpThreadReloadTick } from "../threads/use-thread-reload-tick";

import type { WorkflowEntry, WorkflowStatus } from "./types";

const TERMINAL_STATUSES: ReadonlyArray<WorkflowStatus> = [
  "done",
  "failed",
  "cancelled",
];

function isTerminal(status: WorkflowStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export interface UseNotifyParentInput {
  /** Workflow entries that belong to `parentThreadId`. */
  entries: ReadonlyArray<WorkflowEntry>;
}

export function useNotifyParentOnWorkflowFinish(
  parentThreadId: string | null | undefined,
  input: UseNotifyParentInput,
): void {
  const previouslyRunningRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!parentThreadId) {
      // No parent to watch — keep the ref empty so a later non-null id
      // starts from a clean slate.
      previouslyRunningRef.current = new Set();
      return;
    }

    const prev = previouslyRunningRef.current;
    const currentRunning = new Set<string>();
    const currentTerminal = new Set<string>();

    for (const e of input.entries) {
      if (e.status === "running") {
        currentRunning.add(e.child_thread_id);
      } else if (isTerminal(e.status)) {
        currentTerminal.add(e.child_thread_id);
      }
    }

    let bump = false;
    for (const tid of prev) {
      if (currentRunning.has(tid)) continue; // still running
      // Either transitioned to terminal or disappeared — both mean a
      // workflow finish event the parent chat should refetch for.
      bump = true;
      break;
    }

    if (bump) {
      bumpThreadReloadTick(parentThreadId);
    }

    previouslyRunningRef.current = currentRunning;
  }, [parentThreadId, input.entries]);
}
