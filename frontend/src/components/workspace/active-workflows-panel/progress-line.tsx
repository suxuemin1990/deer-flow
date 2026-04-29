"use client";

import { Progress } from "@/components/ui/progress";

export type ProgressShape =
  | { kind: "bar"; current: number; max: number }
  | { kind: "number"; current: number }
  | { kind: "running" };

export function selectProgressShape(
  progress: Record<string, unknown>,
): ProgressShape {
  const cur = progress.current_round;
  const max = progress.max_rounds;
  if (typeof cur === "number" && typeof max === "number" && max > 0) {
    return { kind: "bar", current: cur, max };
  }
  if (typeof cur === "number") {
    return { kind: "number", current: cur };
  }
  return { kind: "running" };
}

interface Props {
  progress: Record<string, unknown>;
}

export function ProgressLine({ progress }: Props) {
  const shape = selectProgressShape(progress);
  if (shape.kind === "bar") {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">
          round {shape.current}/{shape.max}
        </span>
        <Progress
          value={(shape.current / shape.max) * 100}
          className="h-1"
        />
      </div>
    );
  }
  if (shape.kind === "number") {
    return (
      <span className="text-muted-foreground text-xs">
        round {shape.current}
      </span>
    );
  }
  return (
    <span className="text-muted-foreground text-xs italic">running</span>
  );
}
