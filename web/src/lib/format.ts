import type { Category, LedgerType, OrderStatus, Shipment } from "../api/types";

const TZ = "Asia/Seoul";
const NBSP = " ";
const group = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** `₩ 170,000`, `− ₩ 2,400,000`; `signed` adds `+` to positive values. */
export function krw(amount: number | null | undefined, signed = false): string {
  if (amount === null || amount === undefined) return "—";
  const value = `₩${NBSP}${group.format(Math.abs(amount))}`;
  if (amount < 0) return `−${NBSP}${value}`;
  return signed && amount > 0 ? `+${NBSP}${value}` : value;
}

export function usd(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  const rounded = Math.round(amount);
  const value = `$${NBSP}${group.format(Math.abs(rounded))}`;
  return rounded < 0 ? `−${NBSP}${value}` : value;
}

/** Digits only, for money inputs ("170,000" → 170000). */
export function parseAmount(text: string): number | null {
  const cleaned = text.replace(/[\s,_₩]/g, "");
  if (!/^-?\d+$/.test(cleaned)) return null;
  return Number(cleaned);
}

export function formatAmountInput(text: string, allowNegative = false): string {
  const negative = allowNegative && text.trim().startsWith("-");
  const digits = text.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  if (!digits) return negative ? "-" : "";
  return `${negative ? "-" : ""}${group.format(Number(digits))}`;
}

const dateFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: TZ, day: "numeric", month: "short", year: "numeric" });
const shortFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: TZ, day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const dayKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

const clean = (text: string) => text.replace(/\s?г\.$/, "").replace(/\.$/, "");

export function date(value: string | null | undefined): string {
  return value ? clean(dateFmt.format(new Date(value))) : "—";
}

export function shortDate(value: string | null | undefined): string {
  return value ? clean(shortFmt.format(new Date(value))) : "—";
}

export function dateTime(value: string | null | undefined): string {
  return value ? `${date(value)}, ${timeFmt.format(new Date(value))}` : "—";
}

/** Short moment: «сегодня, 21:33», «вчера, 09:10», «18 окт., 14:05». */
export function moment(value: string | null | undefined): string {
  if (!value) return "—";
  const day = dayKey(value);
  const today = dayKey(new Date().toISOString());
  const yesterday = dayKey(new Date(Date.now() - 86_400_000).toISOString());
  const label = day === today ? "сегодня" : day === yesterday ? "вчера" : shortDate(value);
  return `${label}, ${timeFmt.format(new Date(value))}`;
}

/** Seoul calendar day, for grouping (YYYY-MM-DD). */
export function dayKey(value: string | null | undefined): string {
  return value ? dayKeyFmt.format(new Date(value)) : "";
}

/** Today in Seoul as YYYY-MM-DD (for date inputs). */
export function todayKey(): string {
  return dayKeyFmt.format(new Date());
}

export const STATUS_FLOW: OrderStatus[] = ["new", "bought", "warehouse", "cargo", "delivered"];

export const STATUS_LABEL: Record<OrderStatus, string> = {
  new: "Новый",
  bought: "Выкуплен",
  warehouse: "На складе",
  cargo: "Отправлен",
  delivered: "Доставлен",
  cancelled: "Отменён",
};

export const STATUS_PLURAL: Record<OrderStatus, string> = {
  new: "Новые",
  bought: "Выкуплены",
  warehouse: "Склад",
  cargo: "Карго",
  delivered: "Доставлены",
  cancelled: "Отменены",
};

export const STEP_LABEL: Record<OrderStatus, string> = {
  new: "Заказ",
  bought: "Выкуплен",
  warehouse: "Склад",
  cargo: "Карго",
  delivered: "Доставлен",
  cancelled: "Отменён",
};

export function statusLabel(status: OrderStatus | null): string {
  return status ? STATUS_LABEL[status] : "Неизвестно";
}

export const LEDGER_LABEL: Record<LedgerType, string> = {
  order_charge: "Выкуп",
  order_refund: "Возврат",
  order_rebuy: "Перезаказ",
  deposit: "Пополнение",
  adjustment: "Корректировка",
  shipping_charge: "Доставка",
  watch_charge: "Доставка часов",
  order_discount: "Скидка",
};

export function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function items(count: number): string {
  return `${count} ${plural(count, "товар", "товара", "товаров")}`;
}

export function orderTitle(order: { brand: string | null; model: string | null; title?: string | null }): string {
  return order.title || [order.brand, order.model].filter(Boolean).join(" ") || "Без названия";
}

export function timeOnly(value: string | null | undefined): string {
  return value ? timeFmt.format(new Date(value)) : "";
}

/** Product categories (same codes as crm/domain/categories.py). */
export const CATEGORY_LABEL: Record<Category, string> = {
  shoes: "Обувь",
  clothes: "Одежда",
  watch: "Часы",
  bag: "Сумки",
  accessory: "Аксессуары",
  other: "Другое",
};

/** «L · KR 80», «KR 270», «42»: the usual and the Korean size together. */
export function sizeText(order: { size?: string | null; size_kr?: string | null }): string | null {
  return [order.size, order.size_kr ? `KR ${order.size_kr}` : null].filter(Boolean).join(" · ") || null;
}

/** What the list shows per shipment (owner, 26.10.2026): the admin sees the total
 * charged — delivery plus the watches — like «Итого списано» on the shipment page;
 * the client (no charge fields) sees the delivery cost as before. */
export function shipmentTotal(s: Shipment): number {
  if (s.shipping_charged_krw === undefined && s.watch_charged_krw === undefined) return s.shipping_cost_krw ?? 0;
  return (s.shipping_charged_krw ?? s.shipping_cost_krw ?? 0) + (s.watch_charged_krw ?? 0);
}

/** «$» mode of money inputs (owner, 26.10.2026): dollars typed, won saved by the rate.
 * "1,234.5" → 1234.5; up to two decimals; a leading "-" when negatives are allowed. */
export function parseUsd(text: string): number | null {
  const cleaned = text.replace(/[\s,_$]/g, "");
  if (!/^-?\d+(\.\d{0,2})?$/.test(cleaned)) return null;
  return Number(cleaned);
}

export function formatUsdInput(text: string, allowNegative = false): string {
  const negative = allowNegative && text.trim().startsWith("-");
  const [whole = "", ...rest] = text.replace(/[^\d.]/g, "").split(".");
  const digits = whole.replace(/^0+(?=\d)/, "");
  const head = digits ? group.format(Number(digits)) : rest.length ? "0" : "";
  const tail = rest.length ? `.${rest.join("").slice(0, 2)}` : "";
  return `${negative ? "-" : ""}${head}${tail}`;
}

export function usdToKrw(amount: number, rate: number): number {
  return Math.round(amount * rate);
}
