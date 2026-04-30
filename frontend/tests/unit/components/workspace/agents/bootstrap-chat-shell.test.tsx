// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { BootstrapChatShell } from "@/components/workspace/agents/bootstrap-chat-shell";

// Mock router used by the shell
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Spy on useThreadStream to capture sendMessage + onToolEnd
const sendMessageMock = vi.fn().mockResolvedValue(undefined);
const useThreadStreamMock = vi.fn();
const deleteThreadMock = vi.fn();
vi.mock("@/core/threads/hooks", () => ({
  useThreadStream: (args: unknown) => useThreadStreamMock(args),
  useDeleteThread: () => ({ mutate: deleteThreadMock }),
}));

// Stub agent fetch
vi.mock("@/core/agents/api", () => ({
  getAgent: vi.fn().mockResolvedValue({
    name: "test-agent",
    description: "",
    skills: null,
  }),
}));

// Stub heavy children that pull in streamdown/katex CSS via dynamic chains
vi.mock("@/components/workspace/messages", () => ({
  MessageList: () => null,
}));
vi.mock("@/components/workspace/messages/context", () => ({
  ThreadContext: { Provider: ({ children }: { children: React.ReactNode }) => children },
}));
vi.mock("@/components/workspace/artifacts", () => ({
  ArtifactsProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// Stub i18n so the shell can run outside an I18nProvider in unit tests.
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

describe("BootstrapChatShell", () => {
  test("seeds the conversation with provided message on mount", async () => {
    useThreadStreamMock.mockReturnValue([
      { isLoading: false, messages: [] },
      sendMessageMock,
    ]);

    render(
      <BootstrapChatShell
        agentName="test-agent"
        seedMessage="hello {name}"
        mode="reconfigure"
      />,
    );

    await waitFor(() => {
      expect(sendMessageMock).toHaveBeenCalled();
    });
    const firstCallArgs = sendMessageMock.mock.calls[0]!;
    expect(firstCallArgs[1].text).toContain("test-agent");
  });

  test("does not re-seed on rerender", async () => {
    sendMessageMock.mockClear();
    useThreadStreamMock.mockReturnValue([
      { isLoading: false, messages: [] },
      sendMessageMock,
    ]);

    const { rerender } = render(
      <BootstrapChatShell
        agentName="test-agent"
        seedMessage="hello"
        mode="reconfigure"
      />,
    );
    await waitFor(() => expect(sendMessageMock).toHaveBeenCalledTimes(1));

    rerender(
      <BootstrapChatShell
        agentName="test-agent"
        seedMessage="hello"
        mode="reconfigure"
      />,
    );
    // Still exactly one seed
    expect(sendMessageMock).toHaveBeenCalledTimes(1);
  });

  test("renders header title from props", () => {
    useThreadStreamMock.mockReturnValue([
      { isLoading: false, messages: [] },
      sendMessageMock,
    ]);
    render(
      <BootstrapChatShell
        agentName="test-agent"
        seedMessage="hello"
        mode="reconfigure"
        headerTitle="重新引导：test-agent"
      />,
    );
    expect(
      screen.getByText("重新引导：test-agent"),
    ).toBeInTheDocument();
  });
});
