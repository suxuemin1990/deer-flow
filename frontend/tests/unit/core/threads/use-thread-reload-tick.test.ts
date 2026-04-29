import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  __resetThreadReloadTickForTests,
  bumpThreadReloadTick,
  getThreadReloadTick,
  subscribeThreadReloadTick,
} from "@/core/threads/use-thread-reload-tick";

describe("thread reload tick store", () => {
  beforeEach(() => {
    __resetThreadReloadTickForTests();
  });

  it("starts at 0 for any thread id", () => {
    expect(getThreadReloadTick("t1")).toBe(0);
    expect(getThreadReloadTick("t2")).toBe(0);
  });

  it("bumps the tick for the given thread id only", () => {
    bumpThreadReloadTick("t1");
    expect(getThreadReloadTick("t1")).toBe(1);
    expect(getThreadReloadTick("t2")).toBe(0);

    bumpThreadReloadTick("t1");
    expect(getThreadReloadTick("t1")).toBe(2);

    bumpThreadReloadTick("t2");
    expect(getThreadReloadTick("t2")).toBe(1);
    expect(getThreadReloadTick("t1")).toBe(2);
  });

  it("notifies subscribers when any thread is bumped", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeThreadReloadTick(listener);

    bumpThreadReloadTick("t1");
    expect(listener).toHaveBeenCalledTimes(1);

    bumpThreadReloadTick("t2");
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    bumpThreadReloadTick("t1");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("ignores empty thread ids", () => {
    const listener = vi.fn();
    subscribeThreadReloadTick(listener);

    bumpThreadReloadTick("");
    bumpThreadReloadTick(null as unknown as string);
    bumpThreadReloadTick(undefined as unknown as string);

    expect(listener).not.toHaveBeenCalled();
    expect(getThreadReloadTick("")).toBe(0);
  });
});
