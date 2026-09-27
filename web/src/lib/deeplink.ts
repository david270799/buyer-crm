// Links from Telegram notifications open the Mini App at `?open=<target>`:
// order:n5, shipment:<id> or notifications. Anything else is ignored.

export function deepLinkPath(search: string): string | null {
  const open = new URLSearchParams(search).get("open");
  if (!open) return null;
  if (open === "notifications") return "/notifications";
  const order = /^order:(n\d{1,9})$/i.exec(open);
  if (order) return `/orders/${order[1].toLowerCase()}`;
  const shipment = /^shipment:([A-Za-z0-9_-]{1,64})$/.exec(open);
  if (shipment) return `/shipments/${shipment[1]}`;
  return null;
}

/** The path to open once, with `open` removed from the address bar. */
export function takeDeepLink(): string | null {
  const path = deepLinkPath(window.location.search);
  if (!window.location.search.includes("open=")) return path;
  const params = new URLSearchParams(window.location.search);
  params.delete("open");
  const rest = params.toString();
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`,
  );
  return path;
}
