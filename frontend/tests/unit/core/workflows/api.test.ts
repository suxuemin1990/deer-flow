import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://test.local",
}));

import { cancelActiveWorkflow } from "@/core/workflows/api";

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
