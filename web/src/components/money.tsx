import { ArrowDownLeft, ChevronRight, Gift, RotateCcw, SlidersHorizontal, Truck } from "lucide-react";
import { Link } from "react-router-dom";

import type { Balance, LedgerItem } from "../api/types";
import { dayKey, date, krw, LEDGER_LABEL, shortDate, usd } from "../lib/format";
import { Thumb } from "./orders";
import { Empty } from "./ui";

export function BalanceCard({ balance, to, label = "Баланс" }: { balance: Balance; to?: string; label?: string }) {
  const debt = balance.krw < 0;
  const content = (
    <>
      <div className="label">
        {label}
        {debt && <span className="debt-badge">долг</span>}
      </div>
      <div className="krw num">{krw(balance.krw)}</div>
      <div className="usd num">
        {balance.usd !== null ? usd(balance.usd) : "курс $ не задан"}
        {balance.krw_per_usd ? <span className="tiny"> · 1 $ = {balance.krw_per_usd.toLocaleString("en-US")} ₩</span> : null}
      </div>
      {to && <ChevronRight className="chev" size={20} />}
    </>
  );
  const className = `balance-card ${debt ? "debt" : ""}`;
  return to ? (
    <Link to={to} className={className}>
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  );
}

function EntryIcon({ item }: { item: LedgerItem }) {
  if (item.order) return <Thumb src={item.order.thumbnail_url} alt={item.order.title ?? item.order.id} />;
  const Icon =
    item.type === "deposit"
      ? ArrowDownLeft
      : item.type === "shipping_charge"
        ? Truck
        : item.type === "order_discount"
          ? Gift
        : item.type === "order_refund" || item.type === "order_rebuy"
          ? RotateCcw
          : SlidersHorizontal;
  return (
    <div className="thumb icon">
      <Icon size={18} strokeWidth={1.8} />
    </div>
  );
}

function entryTitle(item: LedgerItem): string {
  if (item.type === "shipping_charge") return item.shipment_id ? `Доставка · ${item.shipment_id}` : "Доставка";
  if (item.order_id) {
    const title = item.order?.title;
    const prefix =
      item.type === "order_refund"
        ? "Возврат"
        : item.type === "order_rebuy"
          ? "Перезаказ"
          : item.type === "order_discount"
            ? (item.comment ?? "Скидка")
            : null;
    return [prefix, item.order_id, title].filter(Boolean).join(" · ");
  }
  return item.type ? LEDGER_LABEL[item.type] : "Операция";
}

/** The order of this entry was deleted: the money history stays, the link goes. */
const orderDeleted = (item: LedgerItem) => Boolean(item.order_id) && !item.order;

function entrySubtitle(item: LedgerItem): string | null {
  if (orderDeleted(item)) return item.comment || "Заказ удалён";
  if (item.order_id || item.type === "shipping_charge") return null;
  return item.comment;
}

export function History({ items }: { items: LedgerItem[] }) {
  if (!items.length) return <Empty title="Операций пока нет" hint="Здесь появятся выкупы, пополнения и доставки." />;
  const groups: { key: string; label: string; items: LedgerItem[] }[] = [];
  for (const item of items) {
    const key = dayKey(item.created_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, label: date(item.created_at), items: [item] });
  }
  return (
    <div>
      {groups.map((group) => (
        <div key={group.key}>
          <div className="day-label">{group.label}</div>
          <div className="card list">
            {group.items.map((item) => {
              const content = (
                <>
                  <EntryIcon item={item} />
                  <div className="grow">
                    <div className="title">{entryTitle(item)}</div>
                    {entrySubtitle(item) && <div className="small muted">{entrySubtitle(item)}</div>}
                    <div className="tiny faint num">после: {krw(item.balance_after)}</div>
                  </div>
                  <div className={`amount ${item.amount_krw > 0 ? "positive" : ""}`}>
                    {krw(item.amount_krw, true)}
                  </div>
                </>
              );
              let target: string | null = null;
              if (item.order_id) target = orderDeleted(item) ? null : `/orders/${item.order_id}`;
              else if (item.shipment_id) target = `/shipments/${item.shipment_id}`;
              return target ? (
                <Link key={item.id} to={target} className="list-item">
                  {content}
                </Link>
              ) : (
                <div key={item.id} className="list-item" style={{ cursor: "default" }}>
                  {content}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <div className="small faint" style={{ textAlign: "center", marginTop: 12 }}>
        Показаны последние {items.length} операций · {shortDate(items[items.length - 1]?.created_at)} — сегодня
      </div>
    </div>
  );
}
