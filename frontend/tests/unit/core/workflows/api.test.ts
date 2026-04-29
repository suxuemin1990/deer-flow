import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://test.local",
}));

import {
  cancelActiveWorkflow,
  fetchActiveWorkflows,
} from "@/core/workflows/api";

describe("fetchActiveWorkflows", () => {
  const fetchSpy = vi.fn();

  beforeEach(() => {
    fetchSpy.mockReset();
    vi.stubGlobal("fetch", fetchSpy);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the active workflows endpoint and parses JSON", async () => {
    const payload = {
      active: [
        {
          thread_id: "c1",
          name: "demo-flow",
          started_at: "2026-01-01T00:00:00+00:00",
          is_done: false,
          _error: null,
          progress: { current_round: 3, max_rounds: 10 },
        },
      ],
    };
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => payload,
    });

    const result = await fetchActiveWorkflows("p1");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://test.local/api/threads/p1/workflows/active",
      { signal: undefined },
    );
    expect(result).toEqual(payload);
  });

  it("URL-encodes the thread id", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ active: [] }),
    });
    await fetchActiveWorkflows("a/b c");
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://test.local/api/threads/a%2Fb%20c/workflows/active",
      { signal: undefined },
    );
  });

  it("throws when response is not ok", async () => {
    fetchSpy.mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });
    await expect(fetchActiveWorkflows("p1")).rejects.toThrow(/HTTP 500/);
  });

  it("forwards the AbortSignal", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ active: [] }),
    });
    const controller = new AbortController();
    await fetchActiveWorkflows("p1", controller.signal);
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://test.local/api/threads/p1/workflows/active",
      { signal: controller.signal },
    );
  });
});

describe("cancelActiveWorkflow", () => {
  const fetchSpy = vi.fn();

  beforeEach(() => {
    fetchSpy.mockReset();
    vi.stubGlobal("fetch", fetchSpy);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to the cancel endpoint and returns the parsed body", async () => {
    fetchSpy.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    });

    const result = await cancelActiveWorkflow("parent", "child");

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://test.local/api/threads/parent/workflows/child/cancel",
      { method: "POST" },
    );
    expect(result).toEqual({ ok: true });
  });

  it("throws on non-ok responses", async () => {
    fetchSpy.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
    await expect(cancelActiveWorkflow("p", "c")).rejects.toThrow(/HTTP 404/);
  });
});
