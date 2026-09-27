import { Ban, Pencil, ShoppingBag, Truck, Warehouse } from "lucide-react";
import { useState } from "react";

import { useBulkStatus } from "../api/hooks";
import type { Order, OrderStatus } from "../api/types";
import { errorText, useToast } from "../components/ui";
import { krw } from "../lib/format";
import { bulkSummary, BuySheet, CancelConfirm, EditOrderSheet, ShipmentSheet } from "./sheets";

type Dialog = "buy" | "cancel" | "edit" | "ship" | null;

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
  const canCancel = status === "new" || ((status === "bought" || status === "warehouse") && !order.shipment_id);
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
        </dl>
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
          {canCancel && (
            <button className="btn danger" onClick={() => setDialog("cancel")}>
              <Ban size={16} /> Отменить
            </button>
          )}
        </div>
      </div>
      {dialog === "buy" && <BuySheet order={order} onClose={() => setDialog(null)} />}
      {dialog === "cancel" && <CancelConfirm order={order} onClose={() => setDialog(null)} />}
      {dialog === "edit" && <EditOrderSheet order={order} onClose={() => setDialog(null)} />}
      {dialog === "ship" && (
        <ShipmentSheet ids={[order.id]} onClose={() => setDialog(null)} onDone={() => setDialog(null)} />
      )}
    </>
  );
}
