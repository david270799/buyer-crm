import { describe, expect, it } from "vitest";

import { deepLinkPath } from "./deeplink";

describe("deep links from notifications", () => {
  it("opens orders, shipments and the feed", () => {
    expect(deepLinkPath("?open=order%3AN5")).toBe("/orders/N5");
    expect(deepLinkPath("?open=order:n125")).toBe("/orders/N125");
    expect(deepLinkPath("?v=2&open=shipment%3ASHP-2026-001")).toBe("/shipments/SHP-2026-001");
    expect(deepLinkPath("?open=notifications")).toBe("/notifications");
    expect(deepLinkPath("?open=prep%3Asc123")).toBe("/prep/sc123");
  });
  it("opens the start parameter of a t.me link from the admin group", () => {
    expect(deepLinkPath("?tgWebAppStartParam=order-N5")).toBe("/orders/N5");
    expect(deepLinkPath("?tgWebAppStartParam=shipment-SHP-2026-001")).toBe("/shipments/SHP-2026-001");
    expect(deepLinkPath("", "#tgWebAppData=x&tgWebAppStartParam=prep-sc123")).toBe("/prep/sc123");
    expect(deepLinkPath("?tgWebAppStartParam=notifications")).toBe("/notifications");
    expect(deepLinkPath("?tgWebAppStartParam=evil")).toBeNull();
  });
  it("ignores anything else", () => {
    expect(deepLinkPath("")).toBeNull();
    expect(deepLinkPath("?open=order:../../admin")).toBeNull();
    expect(deepLinkPath("?open=https://evil.example")).toBeNull();
    expect(deepLinkPath("?open=shipment:a/b")).toBeNull();
  });
});
