// Pictures to send to the client by hand («Поделиться», the owner, 23.10.2026):
// a shipment (tracking code, date, box photo, what is inside) and the balance
// with the operations since the last top-up. Drawn on a canvas in the Mini App,
// so the fonts and photos are the same as on screen. Nothing admin-only here:
// no purchase prices, no profit, no shop links.

import type { Balance, LedgerItem, Order, Shipment } from "../api/types";
import { krw, sizeText, usd } from "./format";

const W = 1080;
const PAD = 48;
const INK = "#111827";
const MUTED = "#6b7280";
const LINE = "#e5e7eb";
const TILE_BG = "#f3f4f6";
const FONT = 'Inter, -apple-system, "SF Pro Text", "Segoe UI", Roboto, sans-serif';

const font = (size: number, weight = 400) => `${weight} ${size}px ${FONT}`;

function loadImage(url: string | null | undefined): Promise<HTMLImageElement | null> {
  if (!url) return Promise.resolve(null);
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  // Drawn by hand: CanvasRenderingContext2D.roundRect is missing in older phones' webviews.
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Draw `img` inside the box: "cover" crops to fill, "contain" fits whole. */
function drawImage(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  x: number,
  y: number,
  w: number,
  h: number,
  mode: "cover" | "contain",
) {
  const scale = mode === "cover" ? Math.max(w / img.width, h / img.height) : Math.min(w / img.width, h / img.height);
  const dw = img.width * scale;
  const dh = img.height * scale;
  ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}

function ellipsis(ctx: CanvasRenderingContext2D, text: string, max: number): string {
  if (ctx.measureText(text).width <= max) return text;
  let cut = text;
  while (cut.length > 1 && ctx.measureText(`${cut}…`).width > max) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}…`;
}

function canvasOf(height: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = Math.ceil(height);
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, W, canvas.height);
  ctx.textBaseline = "top";
  return [canvas, ctx];
}

function toBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Не удалось собрать картинку"))), "image/png"),
  );
}

function longDate(value: string | null | undefined): string {
  if (!value) return "";
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Seoul" })
    .format(new Date(value))
    .replace(" г.", "");
}

function goodsWord(n: number): string {
  const d = n % 10;
  const h = n % 100;
  if (d === 1 && h !== 11) return "товар";
  if (d >= 2 && d <= 4 && (h < 12 || h > 14)) return "товара";
  return "товаров";
}

/** Shipment: «Отправка KR…», date and count, the box photo, then the orders
 * three in a row; a bigger parcel only makes the picture taller. */
export async function shipmentPicture(shipment: Shipment, orders: Order[]): Promise<Blob> {
  await document.fonts?.ready;
  const cols = 3;
  const gap = 24;
  const tile = (W - 2 * PAD - (cols - 1) * gap) / cols;
  const rowH = tile + 112;
  const boxUrl = shipment.photos?.[0]?.photo_url ?? shipment.photo_url;
  const [box, ...photos] = await Promise.all([
    loadImage(boxUrl),
    ...orders.map((o) => loadImage(o.thumbnail_url ?? o.photo_url)),
  ]);
  const boxH = box ? 560 : 0;
  const rows = Math.ceil(orders.length / cols);
  const [canvas, ctx] = canvasOf(PAD + 170 + boxH + rows * rowH + PAD - 24);

  let y = PAD;
  ctx.fillStyle = INK;
  ctx.font = font(56, 700);
  ctx.fillText("Отправка", PAD, y);
  if (shipment.tracking_code) {
    const x = PAD + ctx.measureText("Отправка").width + 22;
    ctx.font = font(46, 600);
    ctx.fillText(ellipsis(ctx, shipment.tracking_code, W - PAD - x), x, y + 8);
  }
  ctx.fillStyle = MUTED;
  ctx.font = font(36);
  const when = longDate(shipment.shipment_date ?? shipment.created_at);
  ctx.fillText([when, `${orders.length} ${goodsWord(orders.length)}`].filter(Boolean).join(" · "), PAD, y + 84);
  y += 170;

  if (box) {
    ctx.save();
    roundRect(ctx, PAD, y, W - 2 * PAD, 520, 28);
    ctx.clip();
    drawImage(ctx, box, PAD, y, W - 2 * PAD, 520, "cover");
    ctx.restore();
    y += boxH;
  }

  orders.forEach((order, i) => {
    const x = PAD + (i % cols) * (tile + gap);
    const top = y + Math.floor(i / cols) * rowH;
    ctx.save();
    roundRect(ctx, x, top, tile, tile, 20);
    ctx.fillStyle = TILE_BG;
    ctx.fill();
    ctx.clip();
    const img = photos[i];
    if (img) drawImage(ctx, img, x + 8, top + 8, tile - 16, tile - 16, "contain");
    ctx.restore();
    roundRect(ctx, x, top, tile, tile, 20);
    ctx.strokeStyle = LINE;
    ctx.lineWidth = 2;
    ctx.stroke();

    const size = sizeText(order);
    ctx.fillStyle = INK;
    ctx.font = font(32, 700);
    ctx.fillText(ellipsis(ctx, [order.id, size].filter(Boolean).join(" · "), tile), x, top + tile + 14);
    ctx.fillStyle = MUTED;
    ctx.font = font(26);
    const name = [order.brand, order.model].filter(Boolean).join(" ");
    if (name) ctx.fillText(ellipsis(ctx, name, tile), x, top + tile + 58);
  });
  return toBlob(canvas);
}

/** The operations since the last top-up (the top-up included), newest first. */
export function sinceLastDeposit(items: LedgerItem[]): LedgerItem[] {
  const index = items.findIndex((item) => item.type === "deposit");
  return index < 0 ? items : items.slice(0, index + 1);
}

function entryText(item: LedgerItem): string {
  if (item.type === "shipping_charge" || item.type === "watch_charge") {
    const code = item.shipment?.tracking_code ?? item.shipment_id;
    return [item.type === "watch_charge" ? "Доставка часов" : "Доставка", code].filter(Boolean).join(" · ");
  }
  if (item.order_id) {
    const prefix =
      item.type === "order_refund"
        ? "Возврат"
        : item.type === "order_rebuy"
          ? "Перезаказ"
          : item.type === "order_discount"
            ? (item.comment ?? "Скидка")
            : null;
    return [prefix, item.order_id, item.order?.title].filter(Boolean).join(" · ");
  }
  if (item.type === "deposit") return "Пополнение";
  if (item.type === "adjustment") return item.comment ? `Корректировка · ${item.comment}` : "Корректировка";
  return item.comment ?? "Операция";
}

/** Balance: a navy card with the balance and the date, then the operations. */
export async function balancePicture(balance: Balance, items: LedgerItem[]): Promise<Blob> {
  await document.fonts?.ready;
  const rowH = 124;
  const thumbs = await Promise.all(
    items.map((item) =>
      loadImage(item.order?.thumbnail_url ?? (item.type === "watch_charge" ? null : item.shipment?.thumbnail_url)),
    ),
  );
  const [canvas, ctx] = canvasOf(PAD + 310 + 60 + items.length * rowH + PAD);

  let y = PAD;
  roundRect(ctx, PAD, y, W - 2 * PAD, 270, 32);
  ctx.fillStyle = "#1f2a3a";
  ctx.fill();
  ctx.fillStyle = "#b9c5d6";
  ctx.font = font(32);
  ctx.fillText(`Баланс · ${longDate(new Date().toISOString())}`, PAD + 40, y + 34);
  ctx.fillStyle = balance.krw < 0 ? "#ffb4a6" : "#ffffff";
  ctx.font = font(84, 700);
  ctx.fillText(krw(balance.krw), PAD + 40, y + 88);
  ctx.fillStyle = "#b9c5d6";
  ctx.font = font(34);
  const rate = balance.krw_per_usd ? ` · 1 $ = ${balance.krw_per_usd.toLocaleString("en-US")} ₩` : "";
  ctx.fillText(balance.usd !== null ? `${usd(balance.usd)}${rate}` : rate.slice(3), PAD + 40, y + 200);
  y += 310;

  ctx.fillStyle = INK;
  ctx.font = font(34, 700);
  ctx.fillText(items.length ? "Операции с последнего пополнения" : "Операций пока нет", PAD, y);
  y += 60;

  items.forEach((item, i) => {
    const thumb = thumbs[i];
    ctx.save();
    roundRect(ctx, PAD, y + 12, 84, 84, 16);
    ctx.fillStyle = TILE_BG;
    ctx.fill();
    ctx.clip();
    if (thumb) drawImage(ctx, thumb, PAD, y + 12, 84, 84, "cover");
    ctx.restore();

    const amount = `${item.amount_krw > 0 ? "+" : "−"} ${krw(Math.abs(item.amount_krw))}`;
    ctx.font = font(34, 700);
    const amountW = ctx.measureText(amount).width;
    ctx.fillStyle = item.amount_krw > 0 ? "#2e6a4e" : INK;
    ctx.fillText(amount, W - PAD - amountW, y + 38);

    const textX = PAD + 108;
    const textMax = W - PAD - amountW - 24 - textX;
    ctx.fillStyle = INK;
    ctx.font = font(32);
    ctx.fillText(ellipsis(ctx, entryText(item), textMax), textX, y + 18);
    ctx.fillStyle = MUTED;
    ctx.font = font(26);
    ctx.fillText(longDate(item.created_at), textX, y + 62);

    y += rowH;
    ctx.fillStyle = "#eef0f3";
    ctx.fillRect(PAD, y - 4, W - 2 * PAD, 2);
  });
  return toBlob(canvas);
}
