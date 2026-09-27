import { describe, expect, it } from "vitest";

import { deepLinkPath } from "./deeplink";

describe("deep links from notifications", () => {
  it("opens orders, shipments and the feed", () => {
    expect(deepLinkPath("?open=order%3An5")).toBe("/orders/n5");
    expect(deepLinkPath("?open=order:N125")).toBe("/orders/n125");
    expect(deepLinkPath("?v=2&open=shipment%3ASHP-2026-001")).toBe("/shipments/SHP-2026-001");
    expect(deepLinkPath("?open=notifications")).toBe("/notifications");
  });
  it("ignores anything else", () => {
    expect(deepLinkPath("")).toBeNull();
    expect(deepLinkPath("?open=order:../../admin")).toBeNull();
    expect(deepLinkPath("?open=https://evil.example")).toBeNull();
    expect(deepLinkPath("?open=shipment:a/b")).toBeNull();
  });
});
