import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getThreadViewedSnapshot,
  hasUnreadFinish,
  markViewed,
  subscribeThreadViewed,
} from "@/core/threads/use-thread-viewed";

describe("hasUnreadFinish", () => {
  it("returns false when finishAt is undefined", () => {
    expect(hasUnreadFinish(undefined, undefined)).toBe(false);
  });

  it("returns false when finishAt is null", () => {
    expect(hasUnreadFinish(null, undefined)).toBe(false);
  });

  it("returns false when finishAt is unparseable", () => {
    expect(hasUnreadFinish("not-a-date", undefined)).toBe(false);
  });

  it("returns false when last viewed is after finishAt", () => {
    expect(
      hasUnreadFinish(
        "2026-04-28T11:59:00Z",
        Date.parse("2026-04-28T12:00:00Z"),
      ),
    ).toBe(false);
  });

  it("returns true when finishAt is after last viewed", () => {
    expect(
      hasUnreadFinish(
        "2026-04-28T12:00:00Z",
        Date.parse("2026-04-28T11:59:00Z"),
      ),
    ).toBe(true);
  });

  it("returns true when finishAt parses and lastViewed is undefined", () => {
    expect(hasUnreadFinish("2026-04-28T12:00:00Z", undefined)).toBe(true);
  });
});

describe("thread viewed store", () => {
  beforeEach(() => {
    // reset module state by overwriting all known threads via markViewed and
    // then snapshotting; since state is module-local we use unique thread ids
    // per test instead.
  });

  it("notifies a subscriber when markViewed is called and snapshot reflects the change", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeThreadViewed(listener);

    const before = getThreadViewedSnapshot();
    expect(before["store-test-1"]).toBeUndefined();

    const t0 = Date.now();
    markViewed("store-test-1");

    expect(listener).toHaveBeenCalledTimes(1);

    const after = getThreadViewedSnapshot();
    expect(after).not.toBe(before); // immutable update -> new reference
    expect(after["store-test-1"]).toBeGreaterThanOrEqual(t0);

    unsubscribe();
  });

  it("notifies multiple subscribers", () => {
    const a = vi.fn();
    const b = vi.fn();
    const unsubA = subscribeThreadViewed(a);
    const unsubB = subscribeThreadViewed(b);

    markViewed("store-test-2");

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);

    unsubA();
    unsubB();
  });

  it("stops notifying after unsubscribe", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeThreadViewed(listener);

    markViewed("store-test-3");
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();

    markViewed("store-test-3");
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
