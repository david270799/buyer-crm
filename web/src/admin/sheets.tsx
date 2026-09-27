import { Camera, Loader2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  uploadImage,
  useBulkStatus,
  useBulkUpdate,
  useBuy,
  useCancel,
  useCreateShipment,
  useMoney,
  useOverview,
  useSettings,
  useUpdateOrder,
  useUpdateShipment,
} from "../api/hooks";
import type { BulkResult, Order, OrderStatus, Shipment } from "../api/types";
import { Confirm, errorText, Field, MoneyInput, Sheet, Switch, useToast } from "../components/ui";
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
          {enabled ? "Сожмём до WebP ~100 КБ, пропорции сохранятся" : "Хранилище фото не настроено"}
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
        <Field label="Бренд">
          <input className="input" value={form.brand} onChange={(e) => set("brand", e.target.value)} />
        </Field>
        <Field label="Модель">
          <input className="input" value={form.model} onChange={(e) => set("model", e.target.value)} />
        </Field>
        <Field label="Размер">
          <input className="input" value={form.size} onChange={(e) => set("size", e.target.value)} />
        </Field>
        <Field label="Ссылка">
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
