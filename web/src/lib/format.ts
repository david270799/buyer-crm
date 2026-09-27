import type { LedgerType, OrderStatus } from "../api/types";

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
  deposit: "Пополнение",
  adjustment: "Корректировка",
  shipping_charge: "Доставка",
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
