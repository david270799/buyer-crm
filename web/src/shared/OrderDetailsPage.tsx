import { AlertTriangle, Copy, ExternalLink, MessageSquare, Package } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useOrder } from "../api/hooks";
import type { Order, Shipment } from "../api/types";
import { PageHead } from "../components/Layout";
import { Photo } from "../components/orders";
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

export function ShipmentLink({ shipment }: { shipment: Shipment }) {
  return (
    <Link to={`/shipments/${shipment.id}`} className="card pad row" style={{ gap: 12 }}>
      <div className="thumb icon">
        <Package size={18} strokeWidth={1.8} />
      </div>
      <div className="grow">
        <div style={{ fontWeight: 600 }}>Отправка #{shipment.shipment_number ?? "—"}</div>
        <div className="small muted">
          {date(shipment.shipment_date ?? shipment.created_at)} · {items(shipment.order_count)}
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
  const { order, shipment } = data;

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
          <Photo src={order.photo_url ?? order.thumbnail_url} alt={orderTitle(order)} className="large contain" />
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
              {order.source_url && (
                <>
                  <dt>Ссылка</dt>
                  <dd>
                    <a href={order.source_url} target="_blank" rel="noopener noreferrer" className="link">
                      Открыть <ExternalLink size={12} style={{ verticalAlign: -1 }} />
                    </a>
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
          <div className="card pad">
            <Timestamps order={order} />
          </div>
        </div>
      </div>
    </>
  );
}
