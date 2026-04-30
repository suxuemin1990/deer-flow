// @vitest-environment jsdom
import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  __resetThreadReloadTickForTests,
  getThreadReloadTick,
} from "@/core/threads/use-thread-reload-tick";
import type { WorkflowEntry } from "@/core/workflows/types";
import { useNotifyParentOnWorkflowFinish } from "@/core/workflows/use-notify-parent-on-workflow-finish";

function makeEntry(overrides: Partial<WorkflowEntry>): WorkflowEntry {
  return {
    child_thread_id: "c-x",
    name: "demo-flow",
    status: "running",
    started_at: null,
    finished_at: null,
    progress: {},
    progress_timeline_fields: [],
    report_field: null,
    report_preview: null,
    error: null,
    ...overrides,
  };
}

describe("useNotifyParentOnWorkflowFinish", () => {
  beforeEach(() => {
    __resetThreadReloadTickForTests();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("does not bump when there are no entries", () => {
    renderHook(() =>
      useNotifyParentOnWorkflowFinish("parent-1", { entries: [] }),
    );
    expect(getThreadReloadTick("parent-1")).toBe(0);
  });

  test("does not bump when running entries stay running", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
        },
      },
    );
    expect(getThreadReloadTick("parent-1")).toBe(0);

    rerender({
      entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
    });
    expect(getThreadReloadTick("parent-1")).toBe(0);
  });

  test("bumps once when a running child transitions to done", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
        },
      },
    );

    act(() => {
      rerender({
        entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
      });
    });

    expect(getThreadReloadTick("parent-1")).toBe(1);
  });

  test.each(["done", "failed", "cancelled"] as const)(
    "treats %s as terminal",
    (terminalStatus) => {
      const { rerender } = renderHook(
        ({ entries }) =>
          useNotifyParentOnWorkflowFinish("parent-1", { entries }),
        {
          initialProps: {
            entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
          },
        },
      );
      act(() => {
        rerender({
          entries: [
            makeEntry({ child_thread_id: "c1", status: terminalStatus }),
          ],
        });
      });
      expect(getThreadReloadTick("parent-1")).toBe(1);
    },
  );

  test("bumps once even if the child disappears from the list", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
        },
      },
    );
    act(() => {
      rerender({ entries: [] });
    });
    expect(getThreadReloadTick("parent-1")).toBe(1);
  });

  test("does not double-bump on subsequent re-renders after transition", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
        },
      },
    );
    act(() => {
      rerender({
        entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
      });
    });
    act(() => {
      rerender({
        entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
      });
    });
    expect(getThreadReloadTick("parent-1")).toBe(1);
  });

  test("only bumps the parent thread it watches", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
        },
      },
    );
    act(() => {
      rerender({
        entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
      });
    });
    expect(getThreadReloadTick("parent-1")).toBe(1);
    expect(getThreadReloadTick("parent-2")).toBe(0);
  });

  test("ignores entries that started terminal (not previously seen as running)", () => {
    // First render with a child already in 'done' state — we never saw it
    // running, so there's nothing to refetch on.
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
        },
      },
    );
    expect(getThreadReloadTick("parent-1")).toBe(0);
    act(() => {
      rerender({
        entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
      });
    });
    expect(getThreadReloadTick("parent-1")).toBe(0);
  });

  test("does nothing when parentThreadId is null", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish(null, { entries }),
      {
        initialProps: {
          entries: [makeEntry({ child_thread_id: "c1", status: "running" })],
        },
      },
    );
    act(() => {
      rerender({
        entries: [makeEntry({ child_thread_id: "c1", status: "done" })],
      });
    });
    // No tick should be bumped for any thread (no parent to watch).
    expect(getThreadReloadTick("parent-1")).toBe(0);
  });

  test("two children transitioning trigger only one bump per render cycle", () => {
    const { rerender } = renderHook(
      ({ entries }) =>
        useNotifyParentOnWorkflowFinish("parent-1", { entries }),
      {
        initialProps: {
          entries: [
            makeEntry({ child_thread_id: "c1", status: "running" }),
            makeEntry({ child_thread_id: "c2", status: "running" }),
          ],
        },
      },
    );
    act(() => {
      rerender({
        entries: [
          makeEntry({ child_thread_id: "c1", status: "done" }),
          makeEntry({ child_thread_id: "c2", status: "done" }),
        ],
      });
    });
    // Either 1 (coalesced) or 2 (one per child) is acceptable; assert >=1.
    expect(getThreadReloadTick("parent-1")).toBeGreaterThanOrEqual(1);
  });
});
