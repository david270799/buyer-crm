import { ArrowDownLeft, ChevronRight, Gift, RotateCcw, SlidersHorizontal, Truck, Watch } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Balance, LedgerItem } from "../api/types";
import { dayKey, date, krw, LEDGER_LABEL, monthSummary, plural, shortDate, usd } from "../lib/format";
import { Thumb } from "./orders";
import { Empty, useSeenAmount } from "./ui";

export function BalanceCard({
  balance,
  to,
  label = "Баланс",
  actions,
}: {
  balance: Balance;
  to?: string;
  label?: string;
  /** Round buttons in the empty right part of the card (finance: top up, adjust). */
  actions?: ReactNode;
}) {
  const debt = balance.krw < 0;
  const { shown, delta } = useSeenAmount("balance", balance.krw);
  const content = (
    <>
      <div className="label">
        {label}
        {debt && <span className="debt-badge">долг</span>}
        {delta !== 0 && (
          <span key={`${delta}:${balance.krw}`} className={`balance-delta ${delta > 0 ? "up" : "down"}`}>{krw(delta, true)}</span>
        )}
      </div>
      <div className="krw num">
        {krw(shown)}
      </div>
      <div className="usd num">
        {balance.usd !== null ? usd(balance.usd) : "курс $ не задан"}
        {balance.krw_per_usd ? <span className="tiny"> · 1 $ = {balance.krw_per_usd.toLocaleString("en-US")} ₩</span> : null}
      </div>
      {to && <ChevronRight className="chev" size={20} />}
      {actions && <div className="balance-actions">{actions}</div>}
    </>
  );
  const className = `balance-card ${debt ? "debt" : ""} ${delta !== 0 ? "changed" : ""}`;
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
  if (item.type !== "watch_charge" && item.shipment?.thumbnail_url)
    return <Thumb src={item.shipment.thumbnail_url} alt="Фото отправки" />;
  const Icon =
    item.type === "deposit"
      ? ArrowDownLeft
      : item.type === "shipping_charge"
        ? Truck
        : item.type === "watch_charge"
          ? Watch
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

function entryTitle(item: LedgerItem): ReactNode {
  if (item.type === "shipping_charge" || item.type === "watch_charge") {
    const code = item.shipment?.tracking_code ?? item.shipment_id;
    return (
      <>
        <span className="shipping-word">{item.type === "watch_charge" ? "Доставка часов" : "Доставка"}</span>
        {code ? <span className="num"> · {code}</span> : null}
      </>
    );
  }
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
  if (item.original_amount_krw !== undefined)
    return `Перезаказ: ${krw(-item.original_amount_krw)} → ${krw(-item.amount_krw)}`;
  if (item.order_id || item.type === "shipping_charge") return null;
  return item.comment;
}

function entryTarget(item: LedgerItem): string | null {
  if (item.order_id) return orderDeleted(item) ? null : `/orders/${item.order_id}`;
  return item.shipment_id ? `/shipments/${item.shipment_id}` : null;
}

/** Wide screen «Баланс» (variant 1, the owner, 27.10.2026): the balance and
 * this month's top-ups, goods and shipping in one strip. */
export function BalanceStrip({ balance, items }: { balance: Balance; items: LedgerItem[] }) {
  const m = monthSummary(items);
  const debt = balance.krw < 0;
  return (
    <div className="balance-strip">
      <div className={`big ${debt ? "debt" : ""}`}>
        <div className="cap">
          Баланс клиента{debt && <span className="debt-badge">долг</span>}
        </div>
        <div className="k num">{krw(balance.krw)}</div>
        <div className="tiny num">
          {balance.usd !== null ? usd(balance.usd) : "курс $ не задан"}
          {balance.krw_per_usd ? ` · 1 $ = ${balance.krw_per_usd.toLocaleString("en-US")} ₩` : ""}
        </div>
      </div>
      <div>
        <div className="cap">Пополнено · {m.month}</div>
        <div className="s num positive">{krw(m.deposits, true)}</div>
        <div className="tiny muted">{m.depositCount ? `${m.depositCount} ${plural(m.depositCount, "перевод", "перевода", "переводов")}` : "пополнений не было"}</div>
      </div>
      <div>
        <div className="cap">За товары · {m.month}</div>
        <div className="s num">{krw(m.goods)}</div>
        <div className="tiny muted">
          {m.orders} {plural(m.orders, "заказ", "заказа", "заказов")}
          {m.refunds ? ` · ${m.refunds} ${plural(m.refunds, "возврат", "возврата", "возвратов")}` : ""}
        </div>
      </div>
      <div>
        <div className="cap">Доставка · {m.month}</div>
        <div className="s num">{krw(m.shipping)}</div>
        <div className="tiny muted">
          {m.shipments} {plural(m.shipments, "отправка", "отправки", "отправок")}
        </div>
      </div>
    </div>
  );
}

/** Wide screen history: date, operation, amount, balance after. */
export function HistoryTable({ items }: { items: LedgerItem[] }) {
  const navigate = useNavigate();
  if (!items.length) return <Empty title="Операций пока нет" hint="Здесь появятся выкупы, пополнения и доставки." />;
  return (
    <div className="card table-wrap">
      <table className="orders ledger">
        <thead>
          <tr>
            <th>Дата</th>
            <th>Операция</th>
            <th className="r">Сумма</th>
            <th className="r">Остаток</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const target = entryTarget(item);
            const sub = entrySubtitle(item);
            return (
              <tr key={item.id} className={target ? "" : "static"} onClick={target ? () => navigate(target) : undefined}>
                <td className="muted nowrap">{shortDate(item.created_at)}</td>
                <td>
                  <div className="ledger-op">
                    <EntryIcon item={item} />
                    <div>
                      <div>{entryTitle(item)}</div>
                      {sub && <div className="small muted">{sub}</div>}
                    </div>
                  </div>
                </td>
                <td className={`r amount ${item.amount_krw > 0 ? "positive" : ""}`}>
                  {item.original_amount_krw !== undefined && item.original_amount_krw !== item.amount_krw && (
                    <s className="amount-was">{krw(item.original_amount_krw, true)}</s>
                  )}
                  {krw(item.amount_krw, true)}
                </td>
                <td className="r muted">{krw(item.balance_after)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
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
                    {item.original_amount_krw !== undefined && item.original_amount_krw !== item.amount_krw && (
                      <s className="amount-was">{krw(item.original_amount_krw, true)}</s>
                    )}
                    {krw(item.amount_krw, true)}
                  </div>
                </>
              );
              const target = entryTarget(item);
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
