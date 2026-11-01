// Links from Telegram notifications open the Mini App at `?open=<target>`:
// order:N5, shipment:<id>, prep:<id> or notifications. In the admin's group
// the link is t.me/<bot>?startapp=order-N5 instead (01.11.2026). Anything
// else is ignored.

/** `?open=…` (private chats), or Telegram's start parameter from a group's
 * t.me/<bot>?startapp=order-N5 link («:» is not allowed there, so «-»). */
function openTarget(search: string, hash = ""): string | null {
  const open = new URLSearchParams(search).get("open");
  if (open) return open;
  const start =
    new URLSearchParams(search).get("tgWebAppStartParam") ??
    new URLSearchParams(hash.replace(/^#/, "")).get("tgWebAppStartParam");
  return start ? start.replace(/^(order|shipment|prep)-/, "$1:") : null;
}

export function deepLinkPath(search: string, hash = ""): string | null {
  const open = openTarget(search, hash);
  if (!open) return null;
  if (open === "notifications") return "/notifications";
  if (open === "showcase") return "/showcase";
  const order = /^order:n(\d{1,9})$/i.exec(open);
  if (order) return `/orders/N${order[1]}`;
  const shipment = /^shipment:([A-Za-z0-9_-]{1,64})$/.exec(open);
  if (shipment) return `/shipments/${shipment[1]}`;
  const prep = /^prep:([A-Za-z0-9_-]{1,64})$/.exec(open);
  if (prep) return `/prep/${prep[1]}`;
  return null;
}

/** The path to open once, with `open` removed from the address bar. */
export function takeDeepLink(): string | null {
  const path = deepLinkPath(window.location.search, window.location.hash);
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
