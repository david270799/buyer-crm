import { describe, expect, it } from "vitest";

import { date, dayKey, formatAmountInput, items, krw, parseAmount, usd } from "./format";

const nbsp = (s: string) => s.replace(/ /g, " ");

describe("money", () => {
  it("formats KRW with sign", () => {
    expect(krw(12_500_000)).toBe(nbsp("₩ 12,500,000"));
    expect(krw(-2_400_000)).toBe(nbsp("− ₩ 2,400,000"));
    expect(krw(5_000, true)).toBe(nbsp("+ ₩ 5,000"));
    expect(krw(null)).toBe("—");
  });
  it("formats USD rounded", () => {
    expect(usd(9259.26)).toBe(nbsp("$ 9,259"));
    expect(usd(-1777.78)).toBe(nbsp("− $ 1,778"));
  });
  it("parses and masks inputs", () => {
    expect(parseAmount("170,000")).toBe(170000);
    expect(parseAmount("₩ 1 000")).toBe(1000);
    expect(parseAmount("abc")).toBeNull();
    expect(formatAmountInput("1700000")).toBe("1,700,000");
    expect(formatAmountInput("-15000", true)).toBe("-15,000");
    expect(formatAmountInput("-15000")).toBe("15,000");
  });
});

describe("dates use Seoul time", () => {
  it("shifts UTC evening to the next Seoul day", () => {
    expect(dayKey("2026-09-26T20:30:00Z")).toBe("2026-09-27");
    expect(date("2026-09-26T20:30:00Z")).toContain("27");
  });
});

describe("plural", () => {
  it("uses Russian forms", () => {
    expect(items(1)).toBe("1 товар");
    expect(items(3)).toBe("3 товара");
    expect(items(8)).toBe("8 товаров");
    expect(items(21)).toBe("21 товар");
    expect(items(12)).toBe("12 товаров");
  });
});
