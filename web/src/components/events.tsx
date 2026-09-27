import {
  AlertTriangle,
  ArrowDownLeft,
  Bell,
  ClipboardList,
  MessageSquare,
  PackageCheck,
  Repeat,
  ShoppingBag,
  SlidersHorizontal,
  Truck,
  Warehouse,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useUnread } from "../api/hooks";
import type { CrmEvent, EventType } from "../api/types";
import { date, dayKey, krw, timeOnly } from "../lib/format";

const ICONS: Record<EventType, LucideIcon> = {
  order_created: ClipboardList,
  order_bought: ShoppingBag,
  order_rebought: Repeat,
  order_cancelled: XCircle,
  order_warehouse: Warehouse,
  order_delivered: PackageCheck,
  order_status: ClipboardList,
  comment: MessageSquare,
  attention: AlertTriangle,
  shipment_sent: Truck,
  shipment_updated: Truck,
  shipping_cost: Truck,
  deposit: ArrowDownLeft,
  adjustment: SlidersHorizontal,
  rate: SlidersHorizontal,
};

export function BellButton() {
  const { data } = useUnread();
  const total = data?.total ?? 0;
  const important = (data?.important ?? 0) > 0;
  return (
    <Link to="/notifications" className="bell" aria-label={`Уведомления${total ? `: ${total} новых` : ""}`}>
      <Bell size={20} strokeWidth={1.8} />
      {total > 0 && <span className={`bell-badge ${important ? "important" : ""}`}>{total > 99 ? "99+" : total}</span>}
    </Link>
  );
}

function target(event: CrmEvent): string | null {
  if (event.order_ids.length === 1) return `/orders/${event.order_ids[0]}`;
  if (event.shipment_id) return `/shipments/${event.shipment_id}`;
  if (event.order_ids.length > 1) return `/orders/${event.order_ids[0]}`;
  if (event.type === "deposit" || event.type === "adjustment") return "/balance";
  return null;
}

export function EventRow({ event, unread, compact }: { event: CrmEvent; unread?: boolean; compact?: boolean }) {
  const navigate = useNavigate();
  const Icon = (event.type && ICONS[event.type]) || Bell;
  const to = target(event);
  return (
    <div
      className={`event ${event.important ? "important" : ""} ${unread ? "unread" : ""} ${to ? "clickable" : ""}`}
      onClick={to ? () => navigate(to) : undefined}
    >
      <div className="event-icon">
        <Icon size={17} strokeWidth={1.8} />
      </div>
      <div className="grow">
        <div className="row between" style={{ alignItems: "flex-start", gap: 8 }}>
          <div className="event-title">{event.title}</div>
          <div className="tiny faint num" style={{ whiteSpace: "nowrap", marginTop: 2 }}>
            {compact ? date(event.created_at) : timeOnly(event.created_at)}
          </div>
        </div>
        {event.body && <div className="event-body">{event.body}</div>}
        {event.amount_krw ? (
          <div className={`small num ${event.amount_krw > 0 ? "positive" : ""}`} style={{ marginTop: 4, fontWeight: 600 }}>
            {krw(event.amount_krw, true)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Events grouped by Seoul day, newest first. */
export function EventFeed({ events, unreadAfter }: { events: CrmEvent[]; unreadAfter?: string | null }) {
  const groups: { key: string; label: string; items: CrmEvent[] }[] = [];
  for (const event of events) {
    const key = dayKey(event.created_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(event);
    else groups.push({ key, label: date(event.created_at), items: [event] });
  }
  return (
    <div>
      {groups.map((group) => (
        <div key={group.key}>
          <div className="day-label">{group.label}</div>
          <div className="card list">
            {group.items.map((event) => (
              <EventRow
                key={event.id}
                event={event}
                unread={
                  !!unreadAfter && !!event.created_at && new Date(event.created_at) > new Date(unreadAfter)
                }
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Order page: its history, compact. */
export function OrderHistory({ events }: { events: CrmEvent[] }) {
  if (!events.length) return null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      <h3>История</h3>
      <div className="card list">
        {events.map((event) => (
          <EventRow key={event.id} event={event} compact />
        ))}
      </div>
    </div>
  );
}
