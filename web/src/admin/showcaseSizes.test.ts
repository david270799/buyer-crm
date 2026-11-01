import { describe, expect, it } from "vitest";

import { typedSizes } from "./Showcase";

describe("sizes typed in for a screenshot card", () => {
  it("splits by commas, else by spaces, without repeats", () => {
    expect(typedSizes("95, 100, 105 (L), 100")).toEqual(["95", "100", "105 (L)"]);
    expect(typedSizes("260 265  270")).toEqual(["260", "265", "270"]);
    expect(typedSizes("  ")).toEqual([]);
  });
});
