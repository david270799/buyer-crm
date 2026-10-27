import { Check, Package, Pencil } from "lucide-react";
import { useState, type MouseEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useShipment, useShipmentDelivered, useShipments } from "../api/hooks";
import type { Order, Shipment } from "../api/types";
import { PageHead, useWide } from "../components/Layout";
import { Thumb } from "../components/orders";
import { PhotoCarousel } from "../components/PhotoCarousel";
import { StatusBadge } from "../components/status";
import { Confirm, Empty, ErrorState, Loading, errorText, useToast } from "../components/ui";
import { date, items, krw, orderTitle, shipmentTotal, sizeText } from "../lib/format";
import { CopyText } from "./OrderDetailsPage";

type Detail = (id: string) => ReactNode;

const plainDetail: Detail = (id) => <ShipmentDetailsPage id={id} />;

export function ShipmentsPage({ detail = plainDetail, newButton }: { detail?: Detail; newButton?: ReactNode }) {
  const wide = useWide();
  const { data, error, isLoading, refetch } = useShipments();
  const [arrived, setArrived] = useState<Shipment | null>(null);
  if (wide && data?.items.length) return <ShipmentsSplit detail={detail} newButton={newButton} />;
  return (
    <>
      {isLoading ? (
        <Loading rows={4} />
      ) : error || !data ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data.items.length ? (
        <Empty title="Отправок пока нет" icon={<Package size={22} />} hint="Когда товары отправят, они появятся здесь." />
      ) : (
        <div className="card list shipments-list">
          {data.items.map((s) => (
            <Link key={s.id} to={`/shipments/${s.id}`} className={`list-item ${s.delivered ? "" : "has-action"}`}>
              {s.thumbnail_url || s.photo_url ? (
                <Thumb src={s.thumbnail_url ?? s.photo_url} alt={s.tracking_code ?? `${s.shipment_number}`} />
              ) : (
                <div className="thumb icon">
                  <Package size={18} strokeWidth={1.8} />
                </div>
              )}
              <div className="grow">
                <div className="title num">{s.tracking_code ?? "Без трек-номера"}</div>
                <div className="small muted">
                  {s.shipment_number ?? "—"} · {date(s.shipment_date ?? s.created_at)} · {items(s.order_count)}
                  {s.weight_kg ? ` · ${s.weight_kg} кг` : ""}
                </div>
              </div>
              <div className="stack" style={{ gap: 4, alignItems: "flex-end" }}>
                <ShipmentStatus delivered={s.delivered} />
                {shipmentTotal(s) ? <div className="amount small muted">{krw(shipmentTotal(s))}</div> : null}
              </div>
              {/* A full-width button under a shipment in transit (the owner, 22.10.2026). */}
              {!s.delivered && <DeliveredButton wide onClick={() => setArrived(s)} />}
            </Link>
          ))}
        </div>
      )}
      {arrived && <DeliveredConfirm shipment={arrived} onClose={() => setArrived(null)} />}
    </>
  );
}

/** «/shipments/:id»: on a wide screen the list stays on the left. */
export function ShipmentRoute({ detail = plainDetail, newButton }: { detail?: Detail; newButton?: ReactNode }) {
  const { id = "" } = useParams();
  const wide = useWide();
  return wide ? <ShipmentsSplit active={id} detail={detail} newButton={newButton} /> : <>{detail(id)}</>;
}

/** Wide screen «Отправки» (variant 3, the owner, 27.10.2026): the list on the
 * left, the chosen shipment (the newest at first) on the right. */
function ShipmentsSplit({ active, detail, newButton }: { active?: string; detail: Detail; newButton?: ReactNode }) {
  const { data } = useShipments();
  const list = data?.items ?? [];
  const current = active ?? list[0]?.id;
  return (
    <div className="ships-split">
      <aside className="ships-side">
        <div className="ships-side-head">
          <span className="cap">Отправки · {list.length}</span>
          {newButton}
        </div>
        {list.map((s) => (
          <Link key={s.id} to={`/shipments/${s.id}`} replace className={`card ship-pick ${s.id === current ? "active" : ""}`}>
            <div className="row between">
              <b className="num">{s.tracking_code ?? "Без трек-номера"}</b>
              <ShipmentStatus delivered={s.delivered} />
            </div>
            <div className="tiny muted">
              {date(s.shipment_date ?? s.created_at)} · {items(s.order_count)}
              {s.weight_kg ? ` · ${s.weight_kg} кг` : ""}
            </div>
            <div className="row between">
              {s.thumbnail_url || s.photo_url ? (
                <Thumb src={s.thumbnail_url ?? s.photo_url} alt={s.tracking_code ?? "Отправка"} />
              ) : (
                <div className="thumb icon">
                  <Package size={18} strokeWidth={1.8} />
                </div>
              )}
              {shipmentTotal(s) ? <b className="num">{krw(shipmentTotal(s))}</b> : null}
            </div>
          </Link>
        ))}
      </aside>
      <section className="card pad ships-detail">{current ? detail(current) : null}</section>
    </div>
  );
}

export function ShipmentDetailsPage({
  onEdit,
  id: shownId,
}: {
  /** Admin buttons in the page head; gets the shipment and its orders. */
  onEdit?: (shipment: Shipment, orders: Order[]) => ReactNode;
  /** Set by the wide split view; otherwise the id comes from the route. */
  id?: string;
}) {
  const params = useParams();
  const id = shownId ?? params.id ?? "";
  const { data, error, isLoading, refetch } = useShipment(id);
  const [arrived, setArrived] = useState(false);
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
        title={shipment.tracking_code ?? "Без трек-номера"}
        sub={
          <span className="row" style={{ gap: 8 }}>
            <span>{shipment.shipment_number ?? "—"}</span>
            <ShipmentStatus delivered={shipment.delivered} />
            {!shipment.delivered && !onEdit && <DeliveredButton onClick={() => setArrived(true)} />}
          </span>
        }
        action={onEdit?.(shipment, orders) ?? null}
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
              {shipment.watch_count ? (
                <>
                  <dt>Часы ⌚</dt>
                  <dd className="num">{shipment.watch_count} шт.</dd>
                </>
              ) : null}
              {shipment.shipping_charged_krw !== undefined && (
                <>
                  {/* Only when it differs from «Доставка» (the owner, 22.10.2026). */}
                  {(shipment.shipping_charged_krw ?? 0) !== (shipment.shipping_cost_krw ?? 0) && (
                    <>
                      <dt>Списано за доставку</dt>
                      <dd>{krw(shipment.shipping_charged_krw)}</dd>
                    </>
                  )}
                  {shipment.watch_charged_krw ? (
                    <>
                      <dt>Списано за часы</dt>
                      <dd>{krw(shipment.watch_charged_krw)}</dd>
                    </>
                  ) : null}
                  <dt className="kv-total">Итого списано</dt>
                  <dd className="kv-total">{krw((shipment.shipping_charged_krw ?? 0) + (shipment.watch_charged_krw ?? 0))}</dd>
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
                    {sizeText(order) ? ` · ${sizeText(order)}` : ""}
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
      {arrived && <DeliveredConfirm shipment={shipment} onClose={() => setArrived(false)} />}
    </>
  );
}

/** Small «Доставлено» button: the one status the client sets (inside a list link, so it stops the click). */
function DeliveredButton({ onClick, wide }: { onClick: () => void; wide?: boolean }) {
  return (
    <button
      type="button"
      className={`btn small delivered-btn ${wide ? "wide" : ""}`}
      onClick={(e: MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        onClick();
      }}
    >
      <Check size={wide ? 16 : 14} /> {wide ? "Отметить доставленной" : "Доставлено"}
    </button>
  );
}

function DeliveredConfirm({ shipment, onClose }: { shipment: Shipment; onClose: () => void }) {
  const toast = useToast();
  const mark = useShipmentDelivered();
  return (
    <Confirm
      title="Отправка пришла?"
      confirmLabel="Да, доставлено"
      busy={mark.isPending}
      onClose={onClose}
      onConfirm={() =>
        mark.mutate(shipment.id, {
          onSuccess: (r) => {
            toast(r.updated.length ? `Доставлено: ${items(r.updated.length)}` : "Уже отмечено");
            onClose();
          },
          onError: (e) => toast(errorText(e), "error"),
        })
      }
    >
      <div className="small">
        Все заказы отправки <b className="num">{shipment.tracking_code ?? shipment.shipment_number ?? ""}</b> станут
        «Доставлен».
      </div>
    </Confirm>
  );
}

/** «В пути» (blue) until every order is delivered, then «Доставлена» (green). */
export function ShipmentStatus({ delivered }: { delivered?: boolean }) {
  return delivered ? (
    <span className="badge s-delivered">Доставлена</span>
  ) : (
    <span className="badge s-cargo">В пути</span>
  );
}

export function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="btn small" onClick={onClick}>
      <Pencil size={14} /> Изменить
    </button>
  );
}
