/**
 * Thread reload-tick store.
 *
 * When a workflow finishes and emits a message to its parent thread out of
 * band (after the parent's normal stream has closed), the LangGraph SDK's
 * `useStream` won't pick up the new checkpoint on its own — it only refetches
 * thread state on threadId change or stream events. This store is a tiny
 * pub/sub bus that lets `useActiveWorkflows` notify the active thread page
 * "your messages are stale; please re-fetch state".
 *
 * Pattern matches `use-thread-viewed.ts`: module-singleton + listener set,
 * exposed to React via `useSyncExternalStore`. No new dep.
 */
import { useSyncExternalStore } from "react";

type Listener = () => void;

let ticks: Record<string, number> = {};
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function subscribeThreadReloadTick(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Record<string, number> {
  return ticks;
}

const EMPTY: Record<string, number> = {};
function getServerSnapshot(): Record<string, number> {
  return EMPTY;
}

export function getThreadReloadTick(threadId: string): number {
  if (!threadId) return 0;
  return ticks[threadId] ?? 0;
}

export function bumpThreadReloadTick(threadId: string): void {
  if (!threadId) return;
  const current = ticks[threadId] ?? 0;
  ticks = { ...ticks, [threadId]: current + 1 };
  emit();
}

/**
 * React hook: subscribe to reload-tick changes for a single thread id.
 * Returns the current tick (0 if never bumped). When the tick changes,
 * the consuming component re-renders.
 */
export function useThreadReloadTick(threadId: string | null | undefined): number {
  const all = useSyncExternalStore(
    subscribeThreadReloadTick,
    getSnapshot,
    getServerSnapshot,
  );
  if (!threadId) return 0;
  return all[threadId] ?? 0;
}

/** Test-only: reset the module-level state between tests. */
export function __resetThreadReloadTickForTests(): void {
  ticks = {};
  listeners.clear();
}
