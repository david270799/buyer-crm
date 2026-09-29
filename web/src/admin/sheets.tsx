import { Camera, Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  recognizePhoto,
  uploadImage,
  useBulkStatus,
  useBulkUpdate,
  useBuy,
  useCancel,
  useCreateShipment,
  useDeleteOrders,
  useDeletePreview,
  useMoney,
  useOrders,
  useOverview,
  useRebuy,
  useSettings,
  useUpdateOrder,
  useUpdateShipment,
} from "../api/hooks";
import type { BulkResult, Order, OrderStatus, PhotoRecognition, Shipment } from "../api/types";
import { Thumb } from "../components/orders";
import { Checkbox, Confirm, errorText, Field, MoneyInput, Sheet, Switch, useToast } from "../components/ui";
import { krw, STATUS_LABEL, todayKey } from "../lib/format";

// --- helpers ------------------------------------------------------------------

export function useBalance(): number | null {
  return useOverview().data?.balance.krw ?? null;
}

function BalancePreview({ delta, label }: { delta: number; label: string }) {
  const balance = useBalance();
  if (!delta) return null;
  return (
    <div className="banner info" style={{ marginTop: 14 }}>
      <div className="stack" style={{ gap: 4 }}>
        <div>
          {label}: <b className="num">{krw(delta, true)}</b>
        </div>
        {balance !== null && (
          <div className="small num">
            Баланс: {krw(balance)} → <b>{krw(balance + delta)}</b>
          </div>
        )}
      </div>
    </div>
  );
}

export function bulkSummary(result: BulkResult, done = "Обновлено"): string {
  const lines: string[] = [];
  if (result.updated.length) lines.push(`${done}: ${result.updated.join(", ")}`);
  if (result.unchanged.length) lines.push(`Без изменений: ${result.unchanged.join(", ")}`);
  if (result.not_found.length) lines.push(`Не найдено: ${result.not_found.join(", ")}`);
  for (const s of result.skipped) lines.push(`${s.order_id}: ${s.reason}`);
  return lines.join("\n") || "Нечего обновлять";
}

// --- photo upload -----------------------------------------------------------------

export interface PhotoValue {
  photo_url: string | null;
  thumbnail_url: string | null;
}

/** Fields Gemini is sure about, for filling a form; empty strings are left out. */
export function recognizedFields(r: PhotoRecognition): { brand?: string; model?: string; size?: string } {
  const fields: { brand?: string; model?: string; size?: string } = {};
  if (r.brand) fields.brand = r.brand;
  if (r.model) fields.model = r.model;
  if (r.size) fields.size = r.size;
  return fields;
}

function recognitionToast(r: PhotoRecognition): string {
  if (r.not_a_product) return "Gemini: на фото не товар — впишите данные вручную";
  if (!r.recognized) return "Gemini не уверен — впишите бренд и модель вручную";
  const name = [r.brand, r.model].filter(Boolean).join(" ");
  return `Gemini: ${name}${r.size ? ` · размер ${r.size}` : ""}`;
}

/** Small AI button next to the order name: Gemini reads the uploaded photo and
 * fills brand, model and size in the form (nothing is saved by itself). */
export function AiFillButton({
  photoUrl,
  onRecognized,
}: {
  photoUrl: string | null;
  onRecognized: (r: PhotoRecognition) => void;
}) {
  const settings = useSettings();
  const toast = useToast();
  const [reading, setReading] = useState(false);
  if (!settings.data?.recognition_enabled) return null;
  const run = async () => {
    if (!photoUrl) {
      toast("Сначала добавьте фото", "error");
      return;
    }
    setReading(true);
    try {
      const result = await recognizePhoto(photoUrl);
      onRecognized(result);
      toast(recognitionToast(result), result.recognized ? undefined : "error");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setReading(false);
    }
  };
  return (
    <button
      type="button"
      className="btn ai-fill"
      onClick={run}
      disabled={reading}
      title="Заполнить по фото (Gemini)"
      aria-label="Заполнить по фото (Gemini)"
    >
      {reading ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />}
    </button>
  );
}

export function PhotoInput({ value, onChange }: { value: PhotoValue; onChange: (v: PhotoValue) => void }) {
  const settings = useSettings();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const enabled = settings.data?.uploads_enabled ?? true;
  return (
    <div className="upload">
      <div className="preview">
        {busy ? (
          <Loader2 className="spin" size={20} />
        ) : value.thumbnail_url || value.photo_url ? (
          <img src={value.thumbnail_url ?? value.photo_url ?? ""} alt="Фото" />
        ) : (
          <Camera size={20} />
        )}
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <label className={`btn small ${enabled ? "" : "disabled"}`} style={{ cursor: enabled ? "pointer" : "default" }}>
          {value.photo_url ? "Заменить фото" : "Добавить фото"}
          <input
            type="file"
            accept="image/*"
            hidden
            disabled={!enabled || busy}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              setBusy(true);
              try {
                onChange(await uploadImage(file));
              } catch (error) {
                toast(errorText(error), "error");
              } finally {
                setBusy(false);
              }
            }}
          />
        </label>
        <div className="tiny faint">
          {enabled ? "Сожмём до WebP, пропорции сохранятся" : "Хранилище фото не настроено"}
        </div>
      </div>
    </div>
  );
}

// --- buy / cancel ---------------------------------------------------------------------

export function BuySheet({ order, onClose }: { order: Order; onClose: () => void }) {
  const toast = useToast();
  const buy = useBuy(order.id);
  const [purchase, setPurchase] = useState<number | null>(order.purchase_price ?? null);
  const [price, setPrice] = useState<number | null>(order.client_price || null);
  const valid = purchase !== null && purchase >= 0 && price !== null && price > 0;
  const profit = valid ? price - purchase : null;
  return (
    <Sheet
      title={`Выкуп ${order.id}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={!valid || buy.isPending}
            onClick={() =>
              buy.mutate(
                { purchase_price: purchase!, client_price: price! },
                {
                  onSuccess: (r) => {
                    toast(r.already_done ? "Уже выкуплен с этими ценами — повторного списания нет" : `Выкуплен. Списано ${krw(price)}`);
                    onClose();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            {buy.isPending ? "Подождите…" : `Выкупить${valid ? ` · ${krw(price)}` : ""}`}
          </button>
        </>
      }
    >
      <div className="form-grid two">
        <Field label="Закупка">
          <MoneyInput value={purchase} onChange={setPurchase} autoFocus />
        </Field>
        <Field label="Цена для клиента">
          <MoneyInput value={price} onChange={setPrice} />
        </Field>
      </div>
      {profit !== null && (
        <div className={`small num ${profit < 0 ? "negative" : "muted"}`} style={{ marginTop: 10 }}>
          Прибыль: {krw(profit)}
          {profit < 0 ? " — отрицательная, проверьте цены" : ""}
        </div>
      )}
      {valid && <BalancePreview delta={-price} label="Будет списано с баланса" />}
    </Sheet>
  );
}

export function RebuySheet({ order, onClose }: { order: Order; onClose: () => void }) {
  const toast = useToast();
  const rebuy = useRebuy(order.id);
  const [purchase, setPurchase] = useState<number | null>(null);
  const [price, setPrice] = useState<number | null>(order.client_price ?? null);
  const [link, setLink] = useState(order.source_url ?? "");
  const [reason, setReason] = useState("");
  const charged = order.charged_amount_krw ?? 0;
  const valid = purchase !== null && purchase >= 0 && price !== null && price > 0;
  const delta = valid ? price - charged : 0; // extra to charge (+) or to refund (−)
  const profit = valid ? price - purchase : null;
  return (
    <Sheet
      title={`Перезаказ ${order.id}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={!valid || rebuy.isPending}
            onClick={() =>
              rebuy.mutate(
                {
                  purchase_price: purchase!,
                  client_price: price!,
                  source_url: link.trim() || null,
                  reason: reason.trim() || null,
                },
                {
                  onSuccess: (r) => {
                    toast(
                      r.already_done
                        ? "Ничего не изменилось — данные те же"
                        : r.change
                          ? `Перезаказан. Баланс: ${krw(r.change.amount_krw, true)}`
                          : "Перезаказан. Цена для клиента та же",
                    );
                    onClose();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            {rebuy.isPending ? "Подождите…" : "Перезаказать"}
          </button>
        </>
      }
    >
      <div className="small muted" style={{ marginBottom: 12 }}>
        Магазин отменил заказ, и вы выкупили товар в другом месте. Сейчас: закупка{" "}
        {krw(order.purchase_price)}, клиенту {krw(order.client_price)}.
      </div>
      <div className="form-grid two">
        <Field label="Новая закупка">
          <MoneyInput value={purchase} onChange={setPurchase} autoFocus />
        </Field>
        <Field label="Цена для клиента">
          <MoneyInput value={price} onChange={setPrice} />
        </Field>
        <div className="full">
          <Field label="Ссылка на новый магазин" hint="Видите только вы">
            <input className="input" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://" />
          </Field>
        </div>
        <div className="full">
          <Field label="Причина" hint="Клиент увидит её в истории заказа и в уведомлении">
            <textarea
              className="textarea"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Магазин отменил заказ: товара нет в наличии"
            />
          </Field>
        </div>
      </div>
      {profit !== null && (
        <div className={`small num ${profit < 0 ? "negative" : "muted"}`} style={{ marginTop: 10 }}>
          Прибыль: {krw(profit)}
        </div>
      )}
      {valid && delta === 0 && (
        <div className="small" style={{ marginTop: 10 }}>
          Цена для клиента не меняется — баланс не изменится.
        </div>
      )}
      {valid && delta !== 0 && (
        <BalancePreview delta={-delta} label={delta > 0 ? "Доплата с баланса" : "Возврат разницы"} />
      )}
    </Sheet>
  );
}

export function CancelConfirm({ order, onClose }: { order: Order; onClose: () => void }) {
  const toast = useToast();
  const cancel = useCancel(order.id);
  const refund = order.charged_amount_krw ?? 0;
  return (
    <Confirm
      title={`Отменить ${order.id}?`}
      confirmLabel={refund ? `Отменить и вернуть ${krw(refund)}` : "Отменить заказ"}
      danger
      busy={cancel.isPending}
      onClose={onClose}
      onConfirm={() =>
        cancel.mutate(undefined, {
          onSuccess: (r) => {
            toast(r.already_done ? "Заказ уже был отменён" : r.refunded_krw ? `Отменён. Возврат ${krw(r.refunded_krw)}` : "Заказ отменён");
            onClose();
          },
          onError: (e) => toast(errorText(e), "error"),
        })
      }
    >
      <div className="muted small">Статус станет «Отменён». Отменить отмену нельзя.</div>
      {refund > 0 ? (
        <BalancePreview delta={refund} label="Вернётся на баланс" />
      ) : (
        <div className="small" style={{ marginTop: 10 }}>
          Списаний по заказу не было — баланс не изменится.
        </div>
      )}
    </Confirm>
  );
}

/** Delete orders everywhere, after showing exactly what will happen (from the server). */
export function DeleteConfirm({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const preview = useDeletePreview(ids);
  const remove = useDeleteOrders();
  const orders = preview.data?.orders ?? [];
  const refund = preview.data?.refund_krw ?? 0;
  const single = ids.length === 1;
  return (
    <Confirm
      title={single ? `Удалить ${ids[0]}?` : `Удалить заказы: ${ids.length} шт.?`}
      confirmLabel={orders.length ? `Удалить${single ? "" : ` (${orders.length})`}` : "Удалить"}
      danger
      busy={remove.isPending || preview.isLoading || !orders.length}
      onClose={onClose}
      onConfirm={() =>
        // mutateAsync, not mutate(..., callbacks): the refreshed order page
        // unmounts this dialog on 404, and per-call callbacks would then be lost.
        remove.mutateAsync(orders.map((o) => o.id)).then(
          (r) => {
            const lines = [`Удалено: ${r.deleted.join(", ")}`];
            if (r.refunded_krw) lines.push(`Возврат ${krw(r.refunded_krw)}`);
            for (const s of r.skipped) lines.push(`${s.order_id}: ${s.reason}`);
            if (r.next_order_id) lines.push(`Следующий заказ: ${r.next_order_id}`);
            toast(lines.join("\n"));
            onDone();
          },
          (e) => toast(errorText(e), "error"),
        )
      }
    >
      {preview.isLoading ? (
        <div className="muted small">Проверяю заказы…</div>
      ) : preview.error ? (
        <div className="banner negative small">{errorText(preview.error)}</div>
      ) : (
        <div className="stack" style={{ gap: 8 }}>
          <div className="muted small">
            Заказ исчезнет у клиента, из списков и истории, фото удалятся. Вернуть нельзя. В журнале действий
            запись останется.
          </div>
          {!single && orders.length > 0 && (
            <div className="small">{orders.map((o) => o.id).join(", ")}</div>
          )}
          {preview.data?.skipped.map((s) => (
            <div key={s.order_id} className="small">
              ⏭ {s.order_id}: {s.reason}
            </div>
          ))}
          {preview.data?.not_found.length ? (
            <div className="small">Не найдено: {preview.data.not_found.join(", ")}</div>
          ) : null}
          {refund > 0 ? (
            <BalancePreview delta={refund} label="Вернётся на баланс" />
          ) : orders.length ? (
            <div className="small">Списаний нет — баланс не изменится.</div>
          ) : (
            <div className="small">Удалять нечего.</div>
          )}
        </div>
      )}
    </Confirm>
  );
}

// --- bulk -------------------------------------------------------------------------------

const BULK_STATUSES: { status: OrderStatus; hint: string }[] = [
  { status: "warehouse", hint: "Товар пришёл на склад" },
  { status: "cargo", hint: "Только для заказов, уже входящих в отправку" },
  { status: "delivered", hint: "Клиент получил товар" },
];

export function BulkStatusSheet({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const mutation = useBulkStatus();
  const [status, setStatus] = useState<OrderStatus>("warehouse");
  return (
    <Sheet
      title={`Статус: ${ids.length} шт.`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { order_ids: ids, status },
                {
                  onSuccess: (r) => {
                    toast(bulkSummary(r));
                    onDone();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            Применить
          </button>
        </>
      }
    >
      <div className="stack">
        {BULK_STATUSES.map((option) => (
          <button
            key={option.status}
            className={`card pad row ${status === option.status ? "selected" : ""}`}
            style={{ textAlign: "left", borderColor: status === option.status ? "var(--accent)" : undefined }}
            onClick={() => setStatus(option.status)}
          >
            <div className="grow">
              <div style={{ fontWeight: 600 }}>{STATUS_LABEL[option.status]}</div>
              <div className="small muted">{option.hint}</div>
            </div>
          </button>
        ))}
        <div className="tiny faint">
          «Выкуплен» и «Отменён» ставятся отдельными действиями, потому что двигают деньги.
        </div>
      </div>
    </Sheet>
  );
}

export function CommentSheet({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const mutation = useBulkUpdate();
  const [internal, setInternal] = useState(false);
  const [text, setText] = useState("");
  return (
    <Sheet
      title={`Комментарий: ${ids.length} шт.`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate(
                { order_ids: ids, [internal ? "internal_comment" : "client_comment"]: text.trim() || null },
                {
                  onSuccess: (r) => {
                    toast(bulkSummary(r));
                    onDone();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            Сохранить
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="chips" style={{ margin: 0, padding: 0 }}>
          <button className={`chip ${!internal ? "active" : ""}`} onClick={() => setInternal(false)}>
            Для клиента
          </button>
          <button className={`chip ${internal ? "active" : ""}`} onClick={() => setInternal(true)}>
            Внутренний
          </button>
        </div>
        <textarea
          className="textarea"
          placeholder={internal ? "Видит только администратор" : "Например: поставка задерживается на 2 дня"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="tiny faint">
          {internal ? "Клиент этот комментарий не увидит." : "Клиент увидит комментарий в карточке заказа."} Пустое
          поле удалит комментарий.
        </div>
      </div>
    </Sheet>
  );
}

export function AttentionSheet({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const mutation = useBulkUpdate();
  const apply = (value: boolean) =>
    mutation.mutate(
      { order_ids: ids, attention_required: value },
      {
        onSuccess: (r) => {
          toast(bulkSummary(r));
          onDone();
        },
        onError: (e) => toast(errorText(e), "error"),
      },
    );
  return (
    <Sheet title={`Внимание: ${ids.length} шт.`} onClose={onClose}>
      <div className="stack">
        <div className="small muted">Отмеченные заказы выделяются у клиента значком «Требуется внимание».</div>
        <button className="btn primary block" disabled={mutation.isPending} onClick={() => apply(true)}>
          Отметить
        </button>
        <button className="btn block" disabled={mutation.isPending} onClick={() => apply(false)}>
          Снять отметку
        </button>
      </div>
    </Sheet>
  );
}

// --- shipments ------------------------------------------------------------------------

interface ShipmentFormValue {
  tracking_code: string;
  box_number: string;
  weight_kg: string;
  shipping_cost_krw: number | null;
  shipment_date: string;
  comment: string;
  photo: PhotoValue;
}

function ShipmentFields({ value, onChange }: { value: ShipmentFormValue; onChange: (v: ShipmentFormValue) => void }) {
  const set = <K extends keyof ShipmentFormValue>(key: K, v: ShipmentFormValue[K]) => onChange({ ...value, [key]: v });
  return (
    <div className="form-grid two">
      <Field label="Трек-номер">
        <input className="input" value={value.tracking_code} onChange={(e) => set("tracking_code", e.target.value.toUpperCase())} placeholder="TRACK123" />
      </Field>
      <Field label="Номер коробки">
        <input className="input" value={value.box_number} onChange={(e) => set("box_number", e.target.value)} placeholder="B-18" />
      </Field>
      <Field label="Вес, кг">
        <input className="input num" inputMode="decimal" value={value.weight_kg} onChange={(e) => set("weight_kg", e.target.value.replace(",", "."))} placeholder="12.5" />
      </Field>
      <Field label="Стоимость доставки" hint="Спишется с баланса клиента">
        <MoneyInput value={value.shipping_cost_krw} onChange={(v) => set("shipping_cost_krw", v)} />
      </Field>
      <Field label="Дата отправки">
        <input className="input" type="date" value={value.shipment_date} onChange={(e) => set("shipment_date", e.target.value)} />
      </Field>
      <div className="field">
        <span>Фото отправки</span>
        <PhotoInput value={value.photo} onChange={(photo) => set("photo", photo)} />
      </div>
      <div className="full">
        <Field label="Комментарий">
          <textarea className="textarea" value={value.comment} onChange={(e) => set("comment", e.target.value)} placeholder="Видит клиент" />
        </Field>
      </div>
    </div>
  );
}

function parseWeight(text: string): number | null | "invalid" {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) && value > 0 ? value : "invalid";
}

/** "+" on the shipments page: pick orders that can be sent, then the usual form. */
export function NewShipmentFlow({ onClose }: { onClose: () => void }) {
  const orders = useOrders({ sort: "newest", limit: 200 });
  const [picked, setPicked] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const candidates = (orders.data?.items ?? []).filter(
    (o) => (o.status === "bought" || o.status === "warehouse") && !o.shipment_id,
  );
  const toggle = (id: string) => setPicked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  if (ready) return <ShipmentSheet ids={picked} onClose={() => setReady(false)} onDone={onClose} />;
  return (
    <Sheet
      title="Новая отправка: заказы"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn primary" disabled={!picked.length} onClick={() => setReady(true)}>
            Далее{picked.length ? ` (${picked.length})` : ""}
          </button>
        </>
      }
    >
      {orders.isLoading ? (
        <div className="muted small">Загрузка…</div>
      ) : !candidates.length ? (
        <div className="muted small">Нет заказов для отправки: нужны выкупленные или на складе, ещё не отправленные.</div>
      ) : (
        <div className="stack" style={{ gap: 8 }}>
          <div className="row between small">
            <span className="muted">Выкуплены или на складе</span>
            <button
              className="btn small ghost"
              onClick={() => setPicked(picked.length === candidates.length ? [] : candidates.map((o) => o.id))}
            >
              {picked.length === candidates.length ? "Снять все" : "Выбрать все"}
            </button>
          </div>
          <div className="list">
            {candidates.map((o) => (
              <div key={o.id} className="list-item" onClick={() => toggle(o.id)}>
                <Checkbox checked={picked.includes(o.id)} onChange={() => toggle(o.id)} label={`Выбрать ${o.id}`} />
                <Thumb src={o.thumbnail_url ?? o.photo_url} alt={o.id} />
                <div className="grow">
                  <div className="title">
                    {o.id} · {[o.brand, o.model].filter(Boolean).join(" ") || "Без названия"}
                  </div>
                  <div className="small muted">
                    {o.status_label ?? ""}
                    {o.size ? ` · размер ${o.size}` : ""}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Sheet>
  );
}

export function ShipmentSheet({ ids, onClose, onDone }: { ids: string[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const create = useCreateShipment();
  const [form, setForm] = useState<ShipmentFormValue>({
    tracking_code: "",
    box_number: "",
    weight_kg: "",
    shipping_cost_krw: null,
    shipment_date: todayKey(),
    comment: "",
    photo: { photo_url: null, thumbnail_url: null },
  });
  const weight = parseWeight(form.weight_kg);
  return (
    <Sheet
      title="Новая отправка"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={create.isPending || weight === "invalid"}
            onClick={() =>
              create.mutate(
                {
                  order_ids: ids,
                  tracking_code: form.tracking_code.trim() || null,
                  box_number: form.box_number.trim() || null,
                  weight_kg: weight === "invalid" ? null : weight,
                  shipping_cost_krw: form.shipping_cost_krw,
                  shipment_date: form.shipment_date || null,
                  comment: form.comment.trim() || null,
                  photo_url: form.photo.photo_url,
                  thumbnail_url: form.photo.thumbnail_url,
                },
                {
                  onSuccess: (r) => {
                    if (!r.shipment) {
                      toast(bulkSummary({ updated: [], unchanged: [], not_found: r.not_found, skipped: r.skipped }), "error");
                      return;
                    }
                    const head = r.created ? `Отправка #${r.shipment.shipment_number} создана` : `Добавлено в отправку #${r.shipment.shipment_number}`;
                    toast([head, bulkSummary({ updated: r.added, unchanged: r.already_in_shipment, not_found: r.not_found, skipped: r.skipped }, "Отправлены")].join("\n"));
                    onDone();
                    navigate(`/shipments/${r.shipment.id}`);
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            {create.isPending ? "Подождите…" : "Создать отправку"}
          </button>
        </>
      }
    >
      <div className="small muted" style={{ marginBottom: 12 }}>
        Заказы: {ids.join(", ")}. Их статус станет «Отправлен».
      </div>
      <ShipmentFields value={form} onChange={setForm} />
      {form.shipping_cost_krw ? <BalancePreview delta={-form.shipping_cost_krw} label="Спишется за доставку" /> : null}
    </Sheet>
  );
}

export function ShipmentEditSheet({ shipment, onClose }: { shipment: Shipment; onClose: () => void }) {
  const toast = useToast();
  const update = useUpdateShipment(shipment.id);
  const [form, setForm] = useState<ShipmentFormValue>({
    tracking_code: shipment.tracking_code ?? "",
    box_number: shipment.box_number ?? "",
    weight_kg: shipment.weight_kg ? String(shipment.weight_kg) : "",
    shipping_cost_krw: shipment.shipping_cost_krw,
    shipment_date: toSeoulDay(shipment.shipment_date),
    comment: shipment.comment ?? "",
    photo: { photo_url: shipment.photo_url, thumbnail_url: shipment.thumbnail_url },
  });
  const weight = parseWeight(form.weight_kg);
  const charged = shipment.shipping_charged_krw ?? 0;
  const delta = -((form.shipping_cost_krw ?? 0) - charged);
  return (
    <Sheet
      title={`Отправка #${shipment.shipment_number}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={update.isPending || weight === "invalid"}
            onClick={() =>
              update.mutate(
                {
                  tracking_code: form.tracking_code.trim() || null,
                  box_number: form.box_number.trim() || null,
                  weight_kg: weight === "invalid" ? null : weight,
                  shipping_cost_krw: form.shipping_cost_krw,
                  shipment_date: form.shipment_date || null,
                  comment: form.comment.trim() || null,
                  photo_url: form.photo.photo_url,
                  thumbnail_url: form.photo.thumbnail_url,
                },
                {
                  onSuccess: (r) => {
                    toast(r.change ? `Сохранено. Баланс: ${krw(r.change.amount_krw, true)}` : "Сохранено");
                    onClose();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            Сохранить
          </button>
        </>
      }
    >
      <ShipmentFields value={form} onChange={setForm} />
      <BalancePreview delta={delta} label={delta < 0 ? "Доплата за доставку" : "Возврат за доставку"} />
    </Sheet>
  );
}

function toSeoulDay(value: string | null): string {
  if (!value) return "";
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

// --- order edit ------------------------------------------------------------------------

export function EditOrderSheet({ order, onClose }: { order: Order; onClose: () => void }) {
  const toast = useToast();
  const update = useUpdateOrder(order.id);
  const editablePrices = order.status === "new" && !order.charged_amount_krw;
  const [form, setForm] = useState({
    brand: order.brand ?? "",
    model: order.model ?? "",
    size: order.size ?? "",
    source_url: order.source_url ?? "",
    client_comment: order.client_comment ?? "",
    internal_comment: order.internal_comment ?? "",
    attention_required: order.attention_required,
    purchase_price: order.purchase_price ?? null,
    client_price: order.client_price ?? null,
    photo: { photo_url: order.photo_url, thumbnail_url: order.thumbnail_url } as PhotoValue,
  });
  const set = <K extends keyof typeof form>(key: K, v: (typeof form)[K]) => setForm({ ...form, [key]: v });
  const text = (v: string) => v.trim() || null;
  return (
    <Sheet
      title={`Изменить ${order.id}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button
            className="btn primary"
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                {
                  brand: text(form.brand),
                  model: text(form.model),
                  size: text(form.size),
                  source_url: text(form.source_url),
                  client_comment: text(form.client_comment),
                  internal_comment: text(form.internal_comment),
                  attention_required: form.attention_required,
                  photo_url: form.photo.photo_url,
                  thumbnail_url: form.photo.thumbnail_url,
                  ...(editablePrices ? { purchase_price: form.purchase_price, client_price: form.client_price } : {}),
                },
                {
                  onSuccess: () => {
                    toast("Сохранено");
                    onClose();
                  },
                  onError: (e) => toast(errorText(e), "error"),
                },
              )
            }
          >
            Сохранить
          </button>
        </>
      }
    >
      <div className="form-grid two">
        <div className="full field">
          <span>Фото</span>
          <PhotoInput value={form.photo} onChange={(photo) => set("photo", photo)} />
        </div>
        <div className="field">
          <span className="field-head">
            Бренд
            <AiFillButton
              photoUrl={form.photo.photo_url}
              onRecognized={(r) => setForm((f) => ({ ...f, ...recognizedFields(r) }))}
            />
          </span>
          <input className="input" aria-label="Бренд" value={form.brand} onChange={(e) => set("brand", e.target.value)} />
        </div>
        <Field label="Модель">
          <input className="input" value={form.model} onChange={(e) => set("model", e.target.value)} />
        </Field>
        <Field label="Размер">
          <input className="input" value={form.size} onChange={(e) => set("size", e.target.value)} />
        </Field>
        <Field label="Ссылка" hint="Видите только вы">
          <input className="input" value={form.source_url} onChange={(e) => set("source_url", e.target.value)} placeholder="https://" />
        </Field>
        {editablePrices && (
          <>
            <Field label="Закупка (черновик)">
              <MoneyInput value={form.purchase_price} onChange={(v) => set("purchase_price", v)} />
            </Field>
            <Field label="Цена клиенту (черновик)" hint="Деньги спишутся только при выкупе">
              <MoneyInput value={form.client_price} onChange={(v) => set("client_price", v)} />
            </Field>
          </>
        )}
        <div className="full">
          <Field label="Комментарий для клиента">
            <textarea className="textarea" value={form.client_comment} onChange={(e) => set("client_comment", e.target.value)} />
          </Field>
        </div>
        <div className="full">
          <Field label="Внутренний комментарий" hint="Клиент не видит">
            <textarea className="textarea" value={form.internal_comment} onChange={(e) => set("internal_comment", e.target.value)} />
          </Field>
        </div>
        <div className="full card pad">
          <Switch
            checked={form.attention_required}
            onChange={(v) => set("attention_required", v)}
            label="Требует внимания"
            hint="Заказ выделится у клиента"
          />
        </div>
      </div>
    </Sheet>
  );
}

// --- money ----------------------------------------------------------------------------------

export function MoneySheet({ kind, onClose }: { kind: "deposit" | "adjust"; onClose: () => void }) {
  const toast = useToast();
  const mutation = useMoney(kind);
  const [amount, setAmount] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [confirming, setConfirming] = useState(false);
  // One key per opened form: a double tap or a retry cannot post twice.
  const [key] = useState(() => crypto.getRandomValues(new Uint32Array(3)).join("-"));
  const adjust = kind === "adjust";
  const valid = amount !== null && amount !== 0 && (adjust || amount > 0) && (!adjust || comment.trim().length > 0);
  const submit = () =>
    mutation.mutate(
      { amount_krw: amount!, comment: comment.trim() || null, idempotency_key: key },
      {
        onSuccess: (r) => {
          toast(r.already_done ? "Операция уже была проведена" : `${adjust ? "Корректировка" : "Пополнение"}: ${krw(amount, true)}`);
          onClose();
        },
        onError: (e) => toast(errorText(e), "error"),
      },
    );
  if (confirming && valid) {
    return (
      <Confirm
        title={adjust ? "Провести корректировку?" : "Пополнить баланс?"}
        confirmLabel={`Подтвердить ${krw(amount, true)}`}
        busy={mutation.isPending}
        onClose={() => setConfirming(false)}
        onConfirm={submit}
      >
        {comment.trim() && <div className="small muted">«{comment.trim()}»</div>}
        <BalancePreview delta={amount!} label={adjust ? "Корректировка" : "Пополнение"} />
      </Confirm>
    );
  }
  return (
    <Sheet
      title={adjust ? "Корректировка баланса" : "Пополнение баланса"}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn primary" disabled={!valid} onClick={() => setConfirming(true)}>
            Продолжить
          </button>
        </>
      }
    >
      <div className="stack">
        <Field label={adjust ? "Сумма (минус — списание)" : "Сумма"}>
          <MoneyInput value={amount} onChange={setAmount} allowNegative={adjust} autoFocus placeholder={adjust ? "-15,000" : "5,000,000"} />
        </Field>
        <Field label={adjust ? "Причина (обязательно)" : "Комментарий"} hint="Клиент увидит комментарий в истории баланса">
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder={adjust ? "Комиссия банка" : "Перевод 26.09"} />
        </Field>
      </div>
    </Sheet>
  );
}
