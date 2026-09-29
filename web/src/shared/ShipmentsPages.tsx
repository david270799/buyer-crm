import { Package, Pencil } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useShipment, useShipments } from "../api/hooks";
import type { Shipment } from "../api/types";
import { PageHead } from "../components/Layout";
import { Thumb } from "../components/orders";
import { PhotoCarousel } from "../components/PhotoCarousel";
import { StatusBadge } from "../components/status";
import { Empty, ErrorState, Loading } from "../components/ui";
import { date, items, krw, orderTitle } from "../lib/format";
import { CopyText } from "./OrderDetailsPage";

export function ShipmentsPage({ action }: { action?: ReactNode }) {
  const { data, error, isLoading, refetch } = useShipments();
  return (
    <>
      <PageHead title="Отправки" sub={data ? `${data.items.length} всего` : undefined} action={action} />
      {isLoading ? (
        <Loading rows={4} />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data.items.length ? (
        <Empty title="Отправок пока нет" icon={<Package size={22} />} hint="Когда товары отправят, они появятся здесь." />
      ) : (
        <div className="card list">
          {data.items.map((s) => (
            <Link key={s.id} to={`/shipments/${s.id}`} className="list-item">
              {s.thumbnail_url || s.photo_url ? (
                <Thumb src={s.thumbnail_url ?? s.photo_url} alt={`Отправка ${s.shipment_number}`} />
              ) : (
                <div className="thumb icon">
                  <Package size={18} strokeWidth={1.8} />
                </div>
              )}
              <div className="grow">
                <div className="title">Отправка #{s.shipment_number ?? "—"}</div>
                <div className="small muted">
                  {date(s.shipment_date ?? s.created_at)} · {items(s.order_count)}
                  {s.weight_kg ? ` · ${s.weight_kg} кг` : ""}
                </div>
              </div>
              {s.shipping_cost_krw ? <div className="amount small muted">{krw(s.shipping_cost_krw)}</div> : null}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

export function ShipmentDetailsPage({ onEdit }: { onEdit?: (shipment: Shipment) => ReactNode }) {
  const { id = "" } = useParams();
  const { data, error, isLoading, refetch } = useShipment(id);
  if (isLoading) return <Loading rows={3} height={120} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  const { shipment, orders } = data;
  const photos =
    shipment.photos?.length || !shipment.photo_url
      ? (shipment.photos ?? [])
      : [{ photo_url: shipment.photo_url, thumbnail_url: shipment.thumbnail_url }];
  return (
    <>
      <PageHead
        title={`Отправка #${shipment.shipment_number ?? "—"}`}
        sub={shipment.id}
        action={onEdit?.(shipment) ?? null}
      />
      <div className="details">
        <div className="stack">
          {photos.length ? (
            <PhotoCarousel photos={photos} alt="Фото отправки" />
          ) : (
            <div className="card pad muted small row">
              <Package size={18} /> Фото отправки пока нет
            </div>
          )}
        </div>
        <div className="stack">
          <div className="card pad">
            <dl className="kv">
              <dt>Трек-номер</dt>
              <dd>{shipment.tracking_code ? <CopyText text={shipment.tracking_code} /> : "—"}</dd>
              <dt>Дата</dt>
              <dd>{date(shipment.shipment_date ?? shipment.created_at)}</dd>
              <dt>Коробка</dt>
              <dd>{shipment.box_number ?? "—"}</dd>
              <dt>Вес</dt>
              <dd>{shipment.weight_kg ? `${shipment.weight_kg} кг` : "—"}</dd>
              <dt>Доставка</dt>
              <dd>{krw(shipment.shipping_cost_krw)}</dd>
              {shipment.shipping_charged_krw !== undefined && (
                <>
                  <dt>Списано за доставку</dt>
                  <dd>{krw(shipment.shipping_charged_krw)}</dd>
                </>
              )}
            </dl>
            {shipment.comment && (
              <>
                <div className="divider" />
                <div className="small">{shipment.comment}</div>
              </>
            )}
          </div>
          <div className="section-head" style={{ marginTop: 8 }}>
            <h2>{items(orders.length)}</h2>
          </div>
          <div className="card list">
            {orders.map((order) => (
              <Link key={order.id} to={`/orders/${order.id}`} className="list-item">
                <Thumb src={order.thumbnail_url ?? order.photo_url} alt={orderTitle(order)} />
                <div className="grow">
                  <div className="title">{orderTitle(order)}</div>
                  <div className="small muted">
                    {order.id}
                    {order.size ? ` · ${order.size}` : ""}
                  </div>
                </div>
                <div className="stack" style={{ gap: 4, alignItems: "flex-end" }}>
                  <div className="amount small">{krw(order.client_price)}</div>
                  <StatusBadge status={order.status} />
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

export function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="btn small" onClick={onClick}>
      <Pencil size={14} /> Изменить
    </button>
  );
}
