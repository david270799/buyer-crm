import { Camera, Copy, Loader2 } from "lucide-react";
import { sizeText } from "../lib/format";
import { useState } from "react";

import { useArrival } from "../api/hooks";
import type { ArrivalCheck, Order } from "../api/types";
import { Sheet, errorText, useToast } from "../components/ui";
import { PhotoInput, type PhotoValue } from "./sheets";

export function arrivalLine(check: ArrivalCheck, order: Order): { text: string; tone: "ok" | "bad" | "muted" } {
  const seen = check.size_seen ?? "—";
  if (check.status === "match") return { text: `✅ Размер совпадает: ${seen}`, tone: "ok" };
  if (check.status === "mismatch")
    return { text: `⚠️ Размер не тот: на фото ${seen}, заказан ${sizeText(order) ?? check.ordered_size ?? "—"}`, tone: "bad" };
  if (check.status === "unclear") return { text: `❓ Размер на фото не прочитан точно (видно: ${seen})`, tone: "muted" };
  if (order.category === "watch") return { text: "⌚ Часы — фото сохранено, проверка не нужна", tone: "muted" };
  if (check.error) return { text: `Проверка не выполнена: ${check.error}`, tone: "muted" };
  return { text: "Размер не проверялся", tone: "muted" };
}

/** Small «Отзыв» block: the Korean review and a copy button (owner, 16.10). */
export function ReviewBlock({ text }: { text: string }) {
  const toast = useToast();
  return (
    <div className="review-block">
      <div className="tiny faint">Отзыв для магазина</div>
      <div className="row" style={{ gap: 8, alignItems: "flex-start" }}>
        <div className="grow review-text" lang="ko">
          {text}
        </div>
        <button
          type="button"
          className="btn small icon-only"
          aria-label="Скопировать отзыв"
          onClick={() =>
            navigator.clipboard?.writeText(text).then(
              () => toast("Отзыв скопирован"),
              () => toast("Не удалось скопировать", "error"),
            )
          }
        >
          <Copy size={15} />
        </button>
      </div>
    </div>
  );
}

/** «Склад» in the admin panel: the warehouse photo, the check, the review, a new photo. */
export function ArrivalPanel({ order }: { order: Order }) {
  const [open, setOpen] = useState(false);
  const canSend = order.status === "bought" || order.status === "warehouse";
  const check = order.arrival_check;
  if (!check && !order.review_ko && !canSend) return null;
  const line = check ? arrivalLine(check, order) : null;
  return (
    <div className="stack" style={{ gap: 8 }}>
      {check && (
        <div className="row" style={{ gap: 10 }}>
          {order.arrival_thumbnail_url && (
            <a href={order.arrival_photo_url ?? order.arrival_thumbnail_url} target="_blank" rel="noopener noreferrer">
              <img className="arrival-thumb" src={order.arrival_thumbnail_url} alt="Фото со склада" />
            </a>
          )}
          <div className={`small grow arrival-${line?.tone}`}>
            {line?.text}
            {check.note && <div className="tiny faint">📝 {check.note}</div>}
          </div>
        </div>
      )}
      {order.review_ko && <ReviewBlock text={order.review_ko} />}
      {canSend && (
        <button className="btn small" style={{ alignSelf: "flex-start" }} onClick={() => setOpen(true)}>
          <Camera size={14} /> {check ? "Новое фото со склада" : "Пришло на склад: фото"}
        </button>
      )}
      {open && <ArrivalSheet order={order} onClose={() => setOpen(false)} />}
    </div>
  );
}

function ArrivalSheet({ order, onClose }: { order: Order; onClose: () => void }) {
  const toast = useToast();
  const arrival = useArrival(order.id);
  const [photo, setPhoto] = useState<PhotoValue>({ photo_url: null, thumbnail_url: null });
  const done = arrival.data;
  return (
    <Sheet
      title={`Пришло на склад · ${order.id}`}
      onClose={onClose}
      footer={
        done ? (
          <button className="btn primary" onClick={onClose}>
            Готово
          </button>
        ) : (
          <>
            <button className="btn ghost" onClick={onClose}>
              Отмена
            </button>
            <button
              className="btn primary"
              disabled={!photo.photo_url || arrival.isPending}
              onClick={() =>
                arrival.mutate(
                  { photo_url: photo.photo_url!, thumbnail_url: photo.thumbnail_url },
                  { onError: (e) => toast(errorText(e), "error") },
                )
              }
            >
              {arrival.isPending ? (
                <>
                  <Loader2 className="spin" size={14} /> Проверяем…
                </>
              ) : (
                "Проверить и на склад"
              )}
            </button>
          </>
        )
      }
    >
      {done ? (
        <div className="stack">
          {done.moved_to_warehouse && <div className="small">🏠 Статус: «На складе»</div>}
          {done.order.arrival_check && (
            <div className={`small arrival-${arrivalLine(done.order.arrival_check, done.order).tone}`}>
              {arrivalLine(done.order.arrival_check, done.order).text}
            </div>
          )}
          {done.note && <div className="small muted">📝 {done.note}</div>}
          {done.review_ko && <ReviewBlock text={done.review_ko} />}
        </div>
      ) : (
        <div className="stack">
          <div className="small muted">
            {order.category === "watch"
              ? "Часы: фото просто сохранится, заказ станет «На складе». Проверки и отзыва нет."
              : `Сфотографируйте этикетку с размером (или сам товар). Gemini сверит размер с заказом${
                  order.size || order.size_kr ? ` (${[order.size, order.size_kr].filter(Boolean).join(" / ")})` : ""
                }, поставит «На складе» и напишет отзыв на корейском.`}
          </div>
          <PhotoInput value={photo} onChange={setPhoto} />
        </div>
      )}
    </Sheet>
  );
}
