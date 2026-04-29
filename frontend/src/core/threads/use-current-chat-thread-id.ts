/**
 * Module-singleton store of the "current chat thread id" — i.e. the
 * thread id the user is actively viewing inside a chat page.
 *
 * Why this exists:
 *   Next.js's `useParams` and `usePathname` are derived from the route
 *   segment captured at route-match time. We deliberately mutate the URL
 *   via `history.replaceState` after creating a brand-new chat (so the
 *   page component does NOT remount and lose its in-flight stream), but
 *   that bypasses Next.js's router — `useParams` keeps returning the
 *   pre-replace value (e.g. literal "new") until the user manually
 *   navigates.
 *
 *   Sidebar widgets (active-workflows panel, etc.) live OUTSIDE the page
 *   route component and need to know the real, current thread id. They
 *   subscribe to this store; the chat page publishes changes via
 *   `setCurrentChatThreadId` whenever its local thread id state moves.
 *
 * Pattern matches `core/threads/use-thread-viewed.ts` and
 * `core/threads/use-thread-reload-tick.ts` — module-scope state plus
 * `useSyncExternalStore` for React subscription. Avoids adding zustand
 * for a single string of state.
 */
import { useSyncExternalStore } from "react";

type Listener = () => void;

let currentChatThreadId: string | null = null;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) {
    listener();
  }
}

export function subscribeCurrentChatThreadId(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getCurrentChatThreadIdSnapshot(): string | null {
  return currentChatThreadId;
}

export function setCurrentChatThreadId(threadId: string | null): void {
  if (currentChatThreadId === threadId) return;
  currentChatThreadId = threadId;
  emit();
}

function getServerSnapshot(): string | null {
  return null;
}

export function useCurrentChatThreadId(): string | null {
  return useSyncExternalStore(
    subscribeCurrentChatThreadId,
    getCurrentChatThreadIdSnapshot,
    getServerSnapshot,
  );
}

// Test-only: reset between tests
export function __resetCurrentChatThreadIdForTests(): void {
  currentChatThreadId = null;
  listeners.clear();
}
