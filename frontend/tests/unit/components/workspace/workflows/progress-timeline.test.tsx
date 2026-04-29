// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { ProgressTimeline } from "@/app/workspace/workflows/[child_thread_id]/_components/progress-timeline";

describe("ProgressTimeline", () => {
  test("renders nothing when fields list is empty", () => {
    const { container } = render(
      <ProgressTimeline values={{}} fields={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  test("renders empty-state placeholder when target field is empty list", () => {
    render(
      <ProgressTimeline values={{ history: [] }} fields={["history"]} />,
    );
    expect(screen.getByText(/no progress yet/i)).toBeInTheDocument();
  });

  test("renders one row per history entry with scalar fields", () => {
    render(
      <ProgressTimeline
        values={{
          history: [
            { round: 1, score: 0.5 },
            { round: 2, score: 0.7 },
          ],
        }}
        fields={["history"]}
      />,
    );
    expect(screen.getByText(/round=1/)).toBeInTheDocument();
    expect(screen.getByText(/score=0\.5/)).toBeInTheDocument();
    expect(screen.getByText(/round=2/)).toBeInTheDocument();
    expect(screen.getByText(/score=0\.7/)).toBeInTheDocument();
  });

  test("hint entries render with 💬 prefix", () => {
    render(
      <ProgressTimeline
        values={{
          history: [{ round: 1, hints: ["try smaller lr"] }],
        }}
        fields={["history"]}
      />,
    );
    expect(screen.getByText(/💬/)).toBeInTheDocument();
    expect(screen.getByText(/try smaller lr/)).toBeInTheDocument();
  });

  test("nested objects render as collapsed JSON", () => {
    render(
      <ProgressTimeline
        values={{
          history: [{ round: 1, metrics: { loss: 0.1, acc: 0.9 } }],
        }}
        fields={["history"]}
      />,
    );
    expect(screen.getByText(/metrics=/)).toBeInTheDocument();
    expect(screen.getByText(/loss/)).toBeInTheDocument();
  });

  test("most recent row gets filled dot, older rows hollow", () => {
    render(
      <ProgressTimeline
        values={{
          history: [
            { round: 1, score: 0.5 },
            { round: 2, score: 0.7 },
          ],
        }}
        fields={["history"]}
      />,
    );
    const filled = screen.getAllByTestId("timeline-dot-filled");
    const hollow = screen.getAllByTestId("timeline-dot-hollow");
    expect(filled.length).toBe(1);
    expect(hollow.length).toBe(1);
  });
});
