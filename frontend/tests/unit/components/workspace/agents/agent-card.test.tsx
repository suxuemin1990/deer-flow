// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("@/core/agents", () => ({
  useDeleteAgent: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

// Stub i18n so the card can run outside an I18nProvider in unit tests.
vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      agents: new Proxy(
        {},
        { get: (_t, prop) => String(prop) },
      ) as unknown as Record<string, string>,
      common: new Proxy(
        {},
        { get: (_t, prop) => String(prop) },
      ) as unknown as Record<string, string>,
    },
  }),
}));

import { AgentCard } from "@/components/workspace/agents/agent-card";
import type { Agent } from "@/core/agents";

const sample: Agent = {
  name: "code-writer",
  description: "writes code",
  skills: null,
  tool_groups: null,
  model: null,
};

describe("AgentCard", () => {
  test("renders reconfigure button", () => {
    render(<AgentCard agent={sample} />);
    expect(
      screen.getByTitle(/重新引导|Reconfigure|reconfigureCardLabel/i),
    ).toBeInTheDocument();
  });

  test("clicking reconfigure routes to /configure", () => {
    pushMock.mockClear();
    render(<AgentCard agent={sample} />);
    const btn = screen.getByTitle(
      /重新引导|Reconfigure|reconfigureCardLabel/i,
    );
    fireEvent.click(btn);
    expect(pushMock).toHaveBeenCalledWith(
      "/workspace/agents/code-writer/configure",
    );
  });
});
