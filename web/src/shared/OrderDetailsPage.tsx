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
import { CATEGORY_LABEL, date, dateTime, items, krw, orderTitle, sizeText } from "../lib/format";

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

/** The order photo; a tap opens it full screen (pinch to zoom). When the
 * warehouse photo exists, a swipe shows it next — admin and client (owner, 16–17.10). */
function OrderPhoto({ order }: { order: Order }) {
  const [open, setOpen] = useState<number | null>(null);
  const [index, setIndex] = useState(0);
  const main = order.photo_url ?? order.thumbnail_url;
  const arrival = order.arrival_photo_url ?? order.arrival_thumbnail_url;
  const slides = [
    main ? { photo_url: main, thumbnail_url: order.thumbnail_url ?? null, label: "Фото заказа" } : null,
    arrival ? { photo_url: arrival, thumbnail_url: order.arrival_thumbnail_url ?? null, label: "Пришло на склад" } : null,
    ...(order.arrival_photos ?? []).map((p) => ({
      photo_url: p.photo_url,
      thumbnail_url: p.thumbnail_url ?? null,
      label: "Пришло на склад",
    })),
  ].filter((s): s is { photo_url: string; thumbnail_url: string | null; label: string } => s !== null);
  if (slides.length < 2) {
    return (
      <>
        <button type="button" className="photo-button" onClick={() => main && setOpen(0)} aria-label="Открыть фото">
          <Photo src={main} alt={orderTitle(order)} className="large contain" />
        </button>
        {open !== null && main && (
          <Lightbox photos={[{ photo_url: main, thumbnail_url: order.thumbnail_url }]} start={0} onClose={() => setOpen(null)} />
        )}
      </>
    );
  }
  return (
    <>
      <div
        className="photo-swipe"
        onScroll={(e) => {
          const el = e.currentTarget;
          setIndex(Math.round(el.scrollLeft / Math.max(1, el.clientWidth)));
        }}
      >
        {slides.map((slide, i) => (
          <button key={`${i}-${slide.photo_url}`} type="button" className="photo-button" onClick={() => setOpen(i)} aria-label={slide.label}>
            <Photo src={slide.photo_url} alt={slide.label} className="large contain" />
            <span className="photo-swipe-label">{slide.label}</span>
          </button>
        ))}
      </div>
      <div className="photo-dots" aria-hidden>
        {slides.map((slide, i) => (
          <i key={`${i}-${slide.photo_url}`} className={i === index ? "active" : ""} />
        ))}
      </div>
      {open !== null && <Lightbox photos={slides} start={open} onClose={() => setOpen(null)} />}
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
              <dd>{sizeText(order) ?? "—"}</dd>
              {order.category && (
                <>
                  <dt>Категория</dt>
                  <dd>{CATEGORY_LABEL[order.category]}</dd>
                </>
              )}
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
