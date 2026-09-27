import { Ban, ExternalLink, Pencil, Repeat, ShoppingBag, Sparkles, Truck, Warehouse } from "lucide-react";
import { useState } from "react";

import { useBulkStatus } from "../api/hooks";
import type { Order, OrderStatus, Recognition } from "../api/types";
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

/** t.me link to the client's message in a supergroup, when the order came from one. */
function telegramLink(order: Order): string | null {
  const chat = order.source_chat_id ? String(order.source_chat_id) : "";
  if (!chat.startsWith("-100") || !order.source_message_id) return null;
  return `https://t.me/c/${chat.slice(4)}/${order.source_message_id}`;
}

function RecognitionInfo({ recognition, link }: { recognition: Recognition; link: string | null }) {
  const percent = recognition.confidence !== null ? Math.round(recognition.confidence * 100) : null;
  let text: string;
  if (!recognition.engine) text = `Без распознавания: ${recognition.error ?? "Gemini не подключён"}`;
  else if (recognition.recognized) text = `Распознано Gemini${percent !== null ? ` · уверенность ${percent}%` : ""}`;
  else text = "Gemini не уверен — впишите бренд и модель вручную";
  return (
    <div className="row small muted" style={{ gap: 8, alignItems: "flex-start" }}>
      <Sparkles size={16} style={{ flex: "none", marginTop: 1 }} />
      <div className="grow">
        {text}
        {recognition.category ? ` · ${recognition.category}` : ""}
        {link && (
          <>
            {" · "}
            <a href={link} target="_blank" rel="noopener noreferrer" className="link">
              сообщение в Telegram <ExternalLink size={12} style={{ verticalAlign: -1 }} />
            </a>
          </>
        )}
      </div>
    </div>
  );
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
        {order.recognition && <RecognitionInfo recognition={order.recognition} link={telegramLink(order)} />}
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
