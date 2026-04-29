import { useCallback, useSyncExternalStore } from "react";

type Listener = () => void;

let lastViewedAt: Record<string, number> = {};
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) {
    listener();
  }
}

export function subscribeThreadViewed(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getThreadViewedSnapshot(): Record<string, number> {
  return lastViewedAt;
}

export function markViewed(threadId: string): void {
  lastViewedAt = { ...lastViewedAt, [threadId]: Date.now() };
  emit();
}

const EMPTY: Record<string, number> = {};

function getServerSnapshot(): Record<string, number> {
  return EMPTY;
}

export function useThreadViewed(): {
  lastViewedAt: Record<string, number>;
  markViewed: (threadId: string) => void;
} {
  const snapshot = useSyncExternalStore(
    subscribeThreadViewed,
    getThreadViewedSnapshot,
    getServerSnapshot,
  );
  const stableMarkViewed = useCallback((threadId: string) => {
    markViewed(threadId);
  }, []);
  return { lastViewedAt: snapshot, markViewed: stableMarkViewed };
}

export function hasUnreadFinish(
  finishAt: string | null | undefined,
  lastViewed: number | undefined,
): boolean {
  if (!finishAt) return false;
  const finishMs = Date.parse(finishAt);
  if (Number.isNaN(finishMs)) return false;
  if (lastViewed === undefined) return true;
  return finishMs > lastViewed;
}
