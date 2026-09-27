import { ClipboardList, PackageCheck, ShoppingBag, Truck, Warehouse, XCircle } from "lucide-react";

import type { OrderStatus } from "../api/types";
import { STATUS_FLOW, STEP_LABEL, shortDate, statusLabel } from "../lib/format";

const ICONS = {
  new: ClipboardList,
  bought: ShoppingBag,
  warehouse: Warehouse,
  cargo: Truck,
  delivered: PackageCheck,
  cancelled: XCircle,
} as const;

export function StatusIcon({ status, size = 16 }: { status: OrderStatus; size?: number }) {
  const Icon = ICONS[status];
  return <Icon size={size} strokeWidth={1.8} />;
}

export function StatusBadge({ status }: { status: OrderStatus | null }) {
  return <span className={`badge s-${status ?? "new"}`}>{statusLabel(status)}</span>;
}

/** Compact `● ● ● ○ ○` progress for cards. */
export function Dots({ status }: { status: OrderStatus | null }) {
  const reached = status ? STATUS_FLOW.indexOf(status) : -1;
  return (
    <span className="dots" aria-label={statusLabel(status)}>
      {STATUS_FLOW.map((step, i) => (
        <span key={step} className={i <= reached ? "on" : ""} />
      ))}
    </span>
  );
}

/** Full stepper: Заказ → Выкуплен → Склад → Карго → Доставлен, with dates. */
export function Stepper({ status, timestamps }: { status: OrderStatus | null; timestamps: Record<string, string> }) {
  if (status === "cancelled") {
    return (
      <div className="banner negative">
        <XCircle size={18} />
        <div>
          Заказ отменён
          {timestamps.cancelled_at && <span className="small"> · {shortDate(timestamps.cancelled_at)}</span>}
        </div>
      </div>
    );
  }
  const reached = status ? STATUS_FLOW.indexOf(status) : -1;
  return (
    <div className="stepper" role="list">
      {STATUS_FLOW.map((step, i) => {
        const when = step === "new" ? timestamps.created_at : timestamps[`${step}_at`];
        const state = i < reached ? "done" : i === reached ? "current" : "";
        return (
          <div key={step} className={`step ${state}`} role="listitem" aria-current={i === reached}>
            <div className="icon">
              <StatusIcon status={step} size={17} />
            </div>
            <div className="name">{STEP_LABEL[step]}</div>
            {when && i <= reached && <div className="when">{shortDate(when)}</div>}
          </div>
        );
      })}
    </div>
  );
}
