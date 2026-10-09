import { AlertTriangle, Copy, MessageSquare, Package } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useOrder } from "../api/hooks";
import type { Order, Shipment } from "../api/types";
import { PageHead } from "../components/Layout";
import { OrderHistory } from "../components/events";
import { Photo } from "../components/orders";
import { Lightbox } from "../components/PhotoCarousel";
import { StatusBadge, Stepper } from "../components/status";
import { ErrorState, Loading, useToast } from "../components/ui";
import { date, dateTime, items, krw, orderTitle } from "../lib/format";

export function CopyText({ text }: { text: string }) {
  const toast = useToast();
  return (
    <button
      className="copy"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => toast("Скопировано"),
          () => toast("Не удалось скопировать", "error"),
        );
      }}
      aria-label={`Скопировать ${text}`}
    >
      {text} <Copy size={13} />
    </button>
  );
}

/** The order photo; a tap opens it full screen (pinch to zoom). */
function OrderPhoto({ order }: { order: Order }) {
  const [open, setOpen] = useState(false);
  const src = order.photo_url ?? order.thumbnail_url;
  return (
    <>
      <button type="button" className="photo-button" onClick={() => src && setOpen(true)} aria-label="Открыть фото">
        <Photo src={src} alt={orderTitle(order)} className="large contain" />
      </button>
      {open && src && (
        <Lightbox photos={[{ photo_url: src, thumbnail_url: order.thumbnail_url }]} start={0} onClose={() => setOpen(false)} />
      )}
    </>
  );
}

export function ShipmentLink({ shipment }: { shipment: Shipment }) {
  return (
    <Link to={`/shipments/${shipment.id}`} className="card pad row" style={{ gap: 12 }}>
      <div className="thumb icon">
        <Package size={18} strokeWidth={1.8} />
      </div>
      <div className="grow">
        <div style={{ fontWeight: 600 }}>{shipment.tracking_code ?? "Отправка без трек-номера"}</div>
        <div className="small muted">
          {shipment.shipment_number ?? "—"} · {date(shipment.shipment_date ?? shipment.created_at)} · {items(shipment.order_count)}
          {shipment.weight_kg ? ` · ${shipment.weight_kg} кг` : ""}
        </div>
      </div>
    </Link>
  );
}

function Timestamps({ order }: { order: Order }) {
  const rows: [string, string][] = [
    ["created_at", "Создан"],
    ["bought_at", "Выкуплен"],
    ["warehouse_at", "На складе"],
    ["cargo_at", "Отправлен"],
    ["delivered_at", "Доставлен"],
    ["cancelled_at", "Отменён"],
  ];
  const present = rows.filter(([key]) => order.timestamps[key]);
  if (!present.length) return null;
  return (
    <dl className="kv small">
      {present.map(([key, label]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{label}</dt>
          <dd>{dateTime(order.timestamps[key])}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Order screen for both roles; `adminPanel` adds prices, edits and actions. */
export function OrderDetailsPage({ adminPanel }: { adminPanel?: (order: Order) => ReactNode }) {
  const { id = "" } = useParams();
  const { data, error, isLoading, refetch } = useOrder(id);
  if (isLoading) return <Loading rows={3} height={140} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  const { order, shipment, history } = data;

  return (
    <>
      <PageHead
        title={orderTitle(order)}
        sub={
          <span className="row" style={{ gap: 8 }}>
            <span className="num">{order.id}</span>
            <StatusBadge status={order.status} />
          </span>
        }
      />
      <div className="details">
        <div className="stack">
          <OrderPhoto order={order} />
        </div>
        <div className="stack">
          {order.attention_required && (
            <div className="banner warning">
              <AlertTriangle size={18} />
              <div>Требуется внимание{order.client_comment ? `: ${order.client_comment}` : ""}</div>
            </div>
          )}
          <div className="card pad stack">
            <div className="row between">
              <div>
                <div className="small muted">{order.brand ?? "Бренд не указан"}</div>
                <div style={{ fontWeight: 600, fontSize: 17 }}>{order.model ?? "—"}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="small muted">Цена</div>
                <div className="num" style={{ fontWeight: 600, fontSize: 17 }}>
                  {krw(order.client_price)}
                </div>
              </div>
            </div>
            <dl className="kv">
              <dt>Размер</dt>
              <dd>{order.size ?? "—"}</dd>
              {order.cargo_code && (
                <>
                  <dt>Трек-номер</dt>
                  <dd>
                    <CopyText text={order.cargo_code} />
                  </dd>
                </>
              )}
            </dl>
          </div>
          <div className="card pad">
            <Stepper status={order.status} timestamps={order.timestamps} />
          </div>
          {order.client_comment && !order.attention_required && (
            <div className="card pad row" style={{ alignItems: "flex-start" }}>
              <MessageSquare size={18} className="muted" />
              <div>{order.client_comment}</div>
            </div>
          )}
          {shipment && <ShipmentLink shipment={shipment} />}
          {adminPanel?.(order)}
          <OrderHistory events={history} />
          <div className="card pad">
            <Timestamps order={order} />
          </div>
        </div>
      </div>
    </>
  );
}
