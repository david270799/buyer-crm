import type { LedgerItem, Shipment } from "../api/types";
import { describe, expect, it } from "vitest";

import { date, dayKey, formatAmountInput, items, krw, monthSummary, parseAmount, parseUsd, formatUsdInput, shipmentTotal, usd, usdToKrw, withUsdNote } from "./format";

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

describe("shipmentTotal", () => {
  const base = { shipping_cost_krw: 73000 } as Shipment;
  it("admin: delivery charged plus the watches", () => {
    expect(shipmentTotal({ ...base, shipping_charged_krw: 73000, watch_charged_krw: 27000 })).toBe(100000);
    expect(shipmentTotal({ ...base, shipping_charged_krw: 0, watch_charged_krw: 13500 })).toBe(13500);
  });
  it("client: only the delivery cost", () => {
    expect(shipmentTotal(base)).toBe(73000);
    expect(shipmentTotal({ ...base, shipping_cost_krw: null })).toBe(0);
  });
});

describe("dollars in money inputs", () => {
  it("parses and formats what is typed", () => {
    expect(parseUsd("1,234.5")).toBe(1234.5);
    expect(parseUsd("100")).toBe(100);
    expect(parseUsd("-15.25")).toBe(-15.25);
    expect(parseUsd("1.234")).toBeNull();
    expect(parseUsd("")).toBeNull();
    expect(formatUsdInput("1234.567")).toBe("1,234.56");
    expect(formatUsdInput("0012")).toBe("12");
    expect(formatUsdInput(".5")).toBe("0.5");
    expect(formatUsdInput("-20", true)).toBe("-20");
  });
  it("converts by the rate, rounded to whole won", () => {
    expect(usdToKrw(100, 1350)).toBe(135000);
    expect(usdToKrw(10.5, 1387.4)).toBe(14568);
    expect(usdToKrw(-20, 1350)).toBe(-27000);
  });
});

describe("withUsdNote", () => {
  it("adds the dollars to a top-up comment", () => {
    expect(withUsdNote("", { dollars: 100, rate: 1350 })).toBe("$100 · 1 $ = 1,350 ₩");
    expect(withUsdNote(" Перевод ", { dollars: 118.5, rate: 1387.5 })).toBe("Перевод · $118.5 · 1 $ = 1,387.5 ₩");
    expect(withUsdNote("Перевод", null)).toBe("Перевод");
  });
});

describe("monthSummary", () => {
  const row = (type: LedgerItem["type"], amount_krw: number, created_at: string, extra: Partial<LedgerItem> = {}): LedgerItem => ({
    id: `${type}${created_at}${amount_krw}`, type, amount_krw, balance_before: 0, balance_after: 0,
    order_id: null, shipment_id: null, comment: null, created_at, order: null, ...extra,
  });
  it("adds up this Seoul month only", () => {
    const items = [
      row("shipping_charge", -71000, "2026-10-22T15:00:00Z", { shipment_id: "S2" }),
      row("watch_charge", -13500, "2026-10-22T15:00:00Z", { shipment_id: "S2" }),
      row("order_refund", 79000, "2026-10-11T15:00:00Z", { order_id: "N1" }),
      row("order_charge", -249000, "2026-10-10T15:00:00Z", { order_id: "N7" }),
      row("order_charge", -79000, "2026-10-08T15:00:00Z", { order_id: "N1" }),
      row("adjustment", -5000, "2026-10-08T15:00:00Z"),
      row("deposit", 8000000, "2026-10-07T13:00:00Z"),
      row("deposit", 100, "2026-09-30T14:00:00Z"), // 30.09 23:00 in Seoul: September
      row("deposit", 200, "2026-09-30T16:00:00Z"), // 01.10 01:00 in Seoul: October
    ];
    const sum = monthSummary(items, new Date("2026-10-27T03:00:00Z"));
    expect(sum).toMatchObject({ deposits: 8000200, depositCount: 2, goods: -249000, orders: 2, refunds: 1, shipping: -84500, shipments: 1 });
    expect(sum.month).toBe("окт");
  });
});
