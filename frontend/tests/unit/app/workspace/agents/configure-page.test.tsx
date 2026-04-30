// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

// Mocks
const useParamsMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => useParamsMock(),
  useRouter: () => ({ push: vi.fn() }),
}));

const getAgentMock = vi.fn();
vi.mock("@/core/agents/api", () => ({
  getAgent: (name: string) => getAgentMock(name),
}));

// Stub the shell so we don't pull in useThreadStream
vi.mock("@/components/workspace/agents/bootstrap-chat-shell", () => ({
  BootstrapChatShell: (props: {
    agentName: string;
    seedMessage: string;
    mode: string;
  }) => (
    <div data-testid="shell">
      {props.agentName}|{props.mode}|{props.seedMessage}
    </div>
  ),
}));

// Stub i18n so the page can run outside an I18nProvider in unit tests.
// (Proxy pattern borrowed from bootstrap-chat-shell.test.tsx, T3 commit 961b7efb.)
vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      agents: new Proxy(
        {},
        { get: (_t, prop) => String(prop) },
      ) as unknown as Record<string, string>,
    },
  }),
}));

import ConfigurePage from "@/app/workspace/agents/[agent_name]/configure/page";

describe("ConfigurePage", () => {
  test("shows not-found state when agent missing", async () => {
    useParamsMock.mockReturnValue({ agent_name: "ghost" });
    getAgentMock.mockRejectedValue(new Error("404"));

    render(<ConfigurePage />);

    await waitFor(() => {
      expect(
        screen.getByText(/找不到该智能体|Agent not found|reconfigureNotFound/i),
      ).toBeInTheDocument();
    });
  });

  test("mounts shell with reconfigure props when agent exists", async () => {
    useParamsMock.mockReturnValue({ agent_name: "code-writer" });
    getAgentMock.mockResolvedValue({ name: "code-writer", description: "" });

    render(<ConfigurePage />);

    await waitFor(() => {
      const shell = screen.getByTestId("shell");
      expect(shell.textContent).toContain("code-writer");
      expect(shell.textContent).toContain("reconfigure");
    });
  });
});
