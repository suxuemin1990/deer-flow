import { expect, test } from "vitest";

import { selectProgressShape } from "@/components/workspace/active-workflows-panel/progress-line";

test("selectProgressShape returns bar when current and max are positive numbers", () => {
  expect(selectProgressShape({ current_round: 3, max_rounds: 10 })).toEqual({
    kind: "bar",
    current: 3,
    max: 10,
  });
});

test("selectProgressShape returns number when only current is a number", () => {
  expect(selectProgressShape({ current_round: 5 })).toEqual({
    kind: "number",
    current: 5,
  });
});

test("selectProgressShape returns running when no recognised fields", () => {
  expect(selectProgressShape({})).toEqual({ kind: "running" });
});

test("selectProgressShape returns running when current is wrong type", () => {
  expect(selectProgressShape({ current_round: "abc" })).toEqual({
    kind: "running",
  });
});

test("selectProgressShape falls back to number when max is zero", () => {
  expect(selectProgressShape({ current_round: 3, max_rounds: 0 })).toEqual({
    kind: "number",
    current: 3,
  });
});
