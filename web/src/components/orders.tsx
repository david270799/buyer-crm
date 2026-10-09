import { AlertTriangle, ImageOff } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { Order } from "../api/types";
import { krw, orderTitle } from "../lib/format";
import { Dots, StatusBadge } from "./status";
import { Checkbox, useLongPress } from "./ui";

export function Photo({
  src,
  alt,
  className = "",
}: {
  src: string | null | undefined;
  alt: string;
  className?: string;
}) {
  return (
    <div className={`photo ${className}`}>
      {src ? (
        <img src={src} alt={alt} loading="lazy" />
      ) : (
        <div className="placeholder">
          <ImageOff size={22} strokeWidth={1.5} />
        </div>
      )}
    </div>
  );
}

export function Thumb({ src, alt }: { src: string | null | undefined; alt: string }) {
  return <div className="thumb">{src ? <img src={src} alt={alt} loading="lazy" /> : null}</div>;
}

export function OrderCard({
  order,
  selectable,
  selected,
  onToggle,
  selecting,
  showCost,
  compact,
}: {
  order: Order;
  selectable?: boolean;
  selected?: boolean;
  onToggle?: () => void;
  /** Something is already selected: a tap anywhere on the card toggles it. */
  selecting?: boolean;
  showCost?: boolean;
  /** «Список»: one compact row instead of a big card. */
  compact?: boolean;
}) {
  const navigate = useNavigate();
  const open = () => navigate(`/orders/${order.id}`);
  const canSelect = Boolean(selectable && onToggle);
  const press = useLongPress(
    () => {
      if (canSelect && !selected) onToggle?.();
    },
    () => (canSelect && selecting ? onToggle?.() : open()),
  );
  const check = selectable && onToggle && (
    <span className="check" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
      <Checkbox checked={!!selected} onChange={onToggle} label={`Выбрать ${order.id}`} />
    </span>
  );
  if (compact) {
    return (
      <article
        className={`order-row st-${order.status ?? "new"} ${selected ? "selected" : ""} ${canSelect ? "no-callout" : ""}`}
        {...(canSelect ? press : { onClick: open })}
      >
        {check}
        <Thumb src={order.thumbnail_url ?? order.photo_url} alt={orderTitle(order)} />
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="row-title">
            <span className="num faint">{order.id}</span> {[order.brand, order.model].filter(Boolean).join(" ") || "Без названия"}
          </div>
          <div className="tiny faint">
            {order.size ? `Размер ${order.size}` : "Размер —"}
            {order.attention_required && (
              <span className="row-attention">
                {" "}
                · <AlertTriangle size={11} style={{ verticalAlign: -1 }} /> внимание
              </span>
            )}
          </div>
        </div>
        <div className="row-side">
          <div className="amount small">{krw(order.client_price)}</div>
          <StatusBadge status={order.status} />
        </div>
      </article>
    );
  }
  return (
    <article
      className={`order-card st-${order.status ?? "new"} ${selected ? "selected" : ""} ${canSelect ? "no-callout" : ""}`}
      {...(canSelect ? press : { onClick: open })}
    >
      {order.attention_required && (
        <span className="badge warn attention">
          <AlertTriangle size={12} /> Внимание
        </span>
      )}
      {check}
      <Photo src={order.thumbnail_url ?? order.photo_url} alt={orderTitle(order)} />
      <div className="body">
        <div className="brand">{order.brand ?? order.id}</div>
        <div className="model">{order.model ?? orderTitle(order)}</div>
        <div className="meta">
          {order.size ? `Размер ${order.size}` : <span className="faint">Размер —</span>}
        </div>
        <div className="price">{krw(order.client_price)}</div>
        {showCost && order.purchase_price != null && (
          <div className="tiny faint num">закупка {krw(order.purchase_price)}</div>
        )}
        <div className="foot">
          <Dots status={order.status} />
          <StatusBadge status={order.status} />
        </div>
      </div>
    </article>
  );
}
