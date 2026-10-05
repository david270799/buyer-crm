import { AlertTriangle, ImageOff } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { Order } from "../api/types";
import { krw, orderTitle, statusLabel } from "../lib/format";
import { Dots } from "./status";
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
}: {
  order: Order;
  selectable?: boolean;
  selected?: boolean;
  onToggle?: () => void;
  /** Something is already selected: a tap anywhere on the card toggles it. */
  selecting?: boolean;
  showCost?: boolean;
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
  return (
    <article
      className={`order-card ${selected ? "selected" : ""} ${canSelect ? "no-callout" : ""}`}
      {...(canSelect ? press : { onClick: open })}
    >
      {order.attention_required && (
        <span className="badge warn attention">
          <AlertTriangle size={12} /> Внимание
        </span>
      )}
      {selectable && onToggle && (
        <span className="check" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
          <Checkbox checked={!!selected} onChange={onToggle} label={`Выбрать ${order.id}`} />
        </span>
      )}
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
          <span>{statusLabel(order.status)}</span>
        </div>
      </div>
    </article>
  );
}
