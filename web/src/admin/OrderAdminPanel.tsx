import { Ban, ExternalLink, Pencil, Repeat, ShoppingBag, Truck, Warehouse } from "lucide-react";
import { useState } from "react";

import { useBulkStatus } from "../api/hooks";
import type { Order, OrderStatus } from "../api/types";
import { errorText, useToast } from "../components/ui";
import { date, krw } from "../lib/format";
import { bulkSummary, BuySheet, CancelConfirm, EditOrderSheet, RebuySheet, ShipmentSheet } from "./sheets";

type Dialog = "buy" | "cancel" | "edit" | "ship" | "rebuy" | null;

function shopName(url: string | null | undefined): string {
  if (!url) return "без ссылки";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function OrderAdminPanel({ order }: { order: Order }) {
  const toast = useToast();
  const [dialog, setDialog] = useState<Dialog>(null);
  const setStatus = useBulkStatus();
  const move = (status: OrderStatus) =>
    setStatus.mutate(
      { order_ids: [order.id], status },
      { onSuccess: (r) => toast(bulkSummary(r)), onError: (e) => toast(errorText(e), "error") },
    );

  const status = order.status;
  const beforeShipping = (status === "bought" || status === "warehouse") && !order.shipment_id;
  const canCancel = status === "new" || beforeShipping;
  const canRebuy = beforeShipping && (order.charged_amount_krw ?? 0) > 0;
  const purchases = order.purchases ?? [];
  const profit = order.profit ?? null;
  return (
    <>
      <div className="card pad stack">
        <div className="row between">
          <h3>Для администратора</h3>
          <button className="btn small ghost" onClick={() => setDialog("edit")}>
            <Pencil size={14} /> Изменить
          </button>
        </div>
        <dl className="kv">
          <dt>Закупка</dt>
          <dd>{krw(order.purchase_price)}</dd>
          <dt>Цена клиенту</dt>
          <dd>{krw(order.client_price)}</dd>
          <dt>Прибыль</dt>
          <dd className={profit !== null && profit < 0 ? "negative" : ""}>{krw(profit)}</dd>
          <dt>Списано с баланса</dt>
          <dd>{krw(order.charged_amount_krw ?? 0)}</dd>
          {order.source_url && (
            <>
              <dt>Ссылка</dt>
              <dd style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                <a href={order.source_url} target="_blank" rel="noopener noreferrer" className="link">
                  {shopName(order.source_url)} <ExternalLink size={12} style={{ verticalAlign: -1 }} />
                </a>
              </dd>
            </>
          )}
        </dl>
        {purchases.length > 1 && (
          <div className="stack" style={{ gap: 6 }}>
            <div className="small muted">Закупки ({purchases.length})</div>
            <ol className="purchases">
              {purchases.map((p, i) => (
                <li key={i} className={p.replaced_at ? "replaced" : ""}>
                  <div className="row between">
                    <span className="grow" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                      {shopName(p.source_url)}
                    </span>
                    <span className="num">{krw(p.purchase_price)}</span>
                  </div>
                  <div className="tiny faint num">
                    {date(p.bought_at)} · клиенту {krw(p.client_price)} ·{" "}
                    {p.replaced_at ? "заменена" : "текущая"}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}
        {order.internal_comment && (
          <div className="banner info small">
            <div>🔒 {order.internal_comment}</div>
          </div>
        )}
        <div className="row wrap" style={{ gap: 8 }}>
          {status === "new" && (
            <button className="btn primary" onClick={() => setDialog("buy")}>
              <ShoppingBag size={16} /> Выкупить
            </button>
          )}
          {status === "bought" && (
            <button className="btn" onClick={() => move("warehouse")} disabled={setStatus.isPending}>
              <Warehouse size={16} /> На склад
            </button>
          )}
          {(status === "bought" || status === "warehouse") && !order.shipment_id && (
            <button className="btn" onClick={() => setDialog("ship")}>
              <Truck size={16} /> В отправку
            </button>
          )}
          {status === "cargo" && (
            <button className="btn" onClick={() => move("delivered")} disabled={setStatus.isPending}>
              Доставлен
            </button>
          )}
          {canRebuy && (
            <button className="btn" onClick={() => setDialog("rebuy")}>
              <Repeat size={16} /> Перезаказ
            </button>
          )}
          {canCancel && (
            <button className="btn danger" onClick={() => setDialog("cancel")}>
              <Ban size={16} /> Отменить
            </button>
          )}
        </div>
      </div>
      {dialog === "buy" && <BuySheet order={order} onClose={() => setDialog(null)} />}
      {dialog === "cancel" && <CancelConfirm order={order} onClose={() => setDialog(null)} />}
      {dialog === "rebuy" && <RebuySheet order={order} onClose={() => setDialog(null)} />}
      {dialog === "edit" && <EditOrderSheet order={order} onClose={() => setDialog(null)} />}
      {dialog === "ship" && (
        <ShipmentSheet ids={[order.id]} onClose={() => setDialog(null)} onDone={() => setDialog(null)} />
      )}
    </>
  );
}
