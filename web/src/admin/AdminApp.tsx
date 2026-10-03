import { LayoutGrid, Package, Plus, Settings, Truck, Wallet } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { useCreateOrder, useOverview, useSetNotifications, useSetRate, useSettings } from "../api/hooks";
import type { NotificationSettings, NotifyLevel, NotifyRecipient, Shipment } from "../api/types";
import { type NavItem, PageHead, Shell } from "../components/Layout";
import { BalanceCard } from "../components/money";
import { OrderCard } from "../components/orders";
import { Empty, ErrorState, errorText, Field, Loading, MoneyInput, Switch, useToast } from "../components/ui";
import { dateTime, krw } from "../lib/format";
import { BalancePage } from "../shared/BalancePage";
import { StatusTiles } from "../shared/filters";
import { NotificationsPage } from "../shared/NotificationsPage";
import { OrderDetailsPage } from "../shared/OrderDetailsPage";
import { EditButton, ShipmentDetailsPage, ShipmentsPage } from "../shared/ShipmentsPages";
import { OrderAdminPanel } from "./OrderAdminPanel";
import { AdminOrdersPage } from "./OrdersPage";
import { PinSettings } from "./pin";
import { ProfitSection } from "./profit";
import { AiFillButton, MoneySheet, NewShipmentFlow, ShipmentDeliveredButton, ShipmentSplitButton, PhotoInput, type PhotoValue, recognizedFields, ShipmentEditSheet, useBalance } from "./sheets";

const NAV: NavItem[] = [
  { to: "/", label: "Сводка", icon: LayoutGrid },
  { to: "/orders", label: "Заказы", icon: Package },
  { to: "/shipments", label: "Отправки", icon: Truck },
  { to: "/finance", label: "Финансы", icon: Wallet },
  { to: "/settings", label: "Настройки", icon: Settings },
];

function Dashboard() {
  const { data, error, isLoading, refetch } = useOverview();
  const [money, setMoney] = useState(false);
  if (isLoading) return <Loading rows={3} height={110} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  const o = data.orders;
  return (
    <>
      <PageHead
        title="Сводка"
        action={
          <Link to="/orders/new" className="btn primary small">
            <Plus size={16} /> Заказ
          </Link>
        }
      />
      <div className="stack" style={{ gap: 12 }}>
        <BalanceCard balance={data.balance} to="/finance" label="Баланс клиента" />
        <div className="kpis">
          <div className="card kpi">
            <div className="small muted">Прибыль за месяц</div>
            <div className="value">{krw(o.profit_month_krw ?? 0)}</div>
          </div>
          <div className="card kpi">
            <div className="small muted">Прибыль всего</div>
            <div className="value">{krw(o.profit_total_krw ?? 0)}</div>
          </div>
          <div className="card kpi">
            <div className="small muted">Активные заказы</div>
            <div className="value">{o.active}</div>
          </div>
          <Link to="/orders?attention=1" className="card kpi">
            <div className="small muted">Требуют внимания</div>
            <div className="value" style={{ color: o.attention_count ? "var(--warning)" : undefined }}>
              {o.attention_count}
            </div>
          </Link>
        </div>
        <StatusTiles counts={o.status_counts} />
        <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setMoney(true)}>
          <Wallet size={16} /> Пополнить баланс
        </button>
      </div>
      <div className="section">
        <div className="section-head">
          <h2>Последние заказы</h2>
          <Link to="/orders">Все {o.total} →</Link>
        </div>
        {data.recent.length ? (
          <div className="order-grid">
            {data.recent.map((order) => (
              <OrderCard key={order.id} order={order} showCost />
            ))}
          </div>
        ) : (
          <Empty title="Заказов пока нет" />
        )}
      </div>
      {money && <MoneySheet kind="deposit" onClose={() => setMoney(false)} />}
    </>
  );
}

function NewOrderPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const create = useCreateOrder();
  const balance = useBalance();
  const [photo, setPhoto] = useState<PhotoValue>({ photo_url: null, thumbnail_url: null });
  const [form, setForm] = useState({ brand: "", model: "", size: "", source_url: "", client_comment: "", internal_comment: "" });
  const [purchase, setPurchase] = useState<number | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [buyNow, setBuyNow] = useState(false);
  const set = (key: keyof typeof form, value: string) => setForm({ ...form, [key]: value });
  const text = (v: string) => v.trim() || null;
  const canBuy = purchase !== null && price !== null && price > 0;
  const submit = () =>
    create.mutate(
      {
        brand: text(form.brand),
        model: text(form.model),
        size: text(form.size),
        source_url: text(form.source_url),
        client_comment: text(form.client_comment),
        internal_comment: text(form.internal_comment),
        purchase_price: purchase,
        client_price: price,
        photo_url: photo.photo_url,
        thumbnail_url: photo.thumbnail_url,
        buy_now: buyNow,
      },
      {
        onSuccess: (r) => {
          toast(r.change ? `Заказ ${r.order.id} создан и выкуплен: ${krw(r.change.amount_krw, true)}` : `Заказ ${r.order.id} создан`);
          navigate(`/orders/${r.order.id}`, { replace: true });
        },
        onError: (e) => toast(errorText(e), "error"),
      },
    );
  return (
    <>
      <PageHead title="Новый заказ" sub="Номер присвоится автоматически" />
      <div className="card pad">
        <div className="form-grid two">
          <div className="full field">
            <span>Фото</span>
            <PhotoInput value={photo} onChange={setPhoto} />
          </div>
          <div className="field">
            <span className="field-head">
              Бренд
              <AiFillButton
                photoUrl={photo.photo_url}
                onRecognized={(r) => setForm((f) => ({ ...f, ...recognizedFields(r) }))}
              />
            </span>
            <input
              className="input"
              aria-label="Бренд"
              value={form.brand}
              onChange={(e) => set("brand", e.target.value)}
              placeholder="Nike"
            />
          </div>
          <Field label="Модель">
            <input className="input" value={form.model} onChange={(e) => set("model", e.target.value)} placeholder="Air Max 95" />
          </Field>
          <Field label="Размер">
            <input className="input" value={form.size} onChange={(e) => set("size", e.target.value)} placeholder="270" />
          </Field>
          <Field label="Ссылка" hint="Видите только вы">
            <input className="input" value={form.source_url} onChange={(e) => set("source_url", e.target.value)} placeholder="https://" />
          </Field>
          <Field label="Закупка">
            <MoneyInput value={purchase} onChange={setPurchase} />
          </Field>
          <Field label="Цена для клиента">
            <MoneyInput value={price} onChange={setPrice} />
          </Field>
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
              checked={buyNow}
              onChange={setBuyNow}
              label="Сразу выкупить"
              hint={buyNow && canBuy ? `Спишется ${krw(price)}${balance !== null ? ` · баланс станет ${krw(balance - (price ?? 0))}` : ""}` : "Статус «Выкуплен», цена клиенту спишется с баланса"}
            />
          </div>
        </div>
        <div className="actions" style={{ display: "flex", gap: 8, marginTop: 18 }}>
          <button className="btn ghost" onClick={() => navigate(-1)}>
            Отмена
          </button>
          <button className="btn primary grow" disabled={create.isPending || (buyNow && !canBuy)} onClick={submit}>
            {create.isPending ? "Сохраняем…" : buyNow ? "Создать и выкупить" : "Создать заказ"}
          </button>
        </div>
      </div>
    </>
  );
}

function AdminShipmentsPage() {
  const [creating, setCreating] = useState(false);
  return (
    <>
      <ShipmentsPage
        action={
          <button className="btn primary small" onClick={() => setCreating(true)} aria-label="Новая отправка">
            <Plus size={16} /> Новая
          </button>
        }
      />
      {creating && <NewShipmentFlow onClose={() => setCreating(false)} />}
    </>
  );
}

function FinancePage() {
  const [sheet, setSheet] = useState<"deposit" | "adjust" | null>(null);
  return (
    <>
      <BalancePage
        title="Финансы"
        extra={<ProfitSection />}
        actions={
          <div className="row" style={{ gap: 6 }}>
            <button className="btn primary small" onClick={() => setSheet("deposit")}>
              Пополнить
            </button>
            <button className="btn small" onClick={() => setSheet("adjust")}>
              Корректировка
            </button>
          </div>
        }
      />
      {sheet && <MoneySheet kind={sheet} onClose={() => setSheet(null)} />}
    </>
  );
}

const RECIPIENTS: { value: NotifyRecipient; label: string }[] = [
  { value: "off", label: "Выключены" },
  { value: "admins", label: "Только мне" },
  { value: "client", label: "Клиенту" },
];

const LEVELS: { value: NotifyLevel; label: string }[] = [
  { value: "important", label: "Только важные" },
  { value: "all", label: "Все" },
];

function NotificationsCard({ settings }: { settings: NotificationSettings }) {
  const toast = useToast();
  const save = useSetNotifications();
  const change = (body: { recipient?: NotifyRecipient; level?: NotifyLevel }) =>
    save.mutate(body, {
      onSuccess: () => toast("Сохранено"),
      onError: (e) => toast(errorText(e), "error"),
    });
  const on = settings.recipient !== "off";
  return (
    <div className="card pad stack">
      <h3>Уведомления в Telegram</h3>
      <div className="small muted">
        Бот пишет в личку о том же, что появляется в колокольчике: без закупочных цен и внутренних
        комментариев. «Только мне» — чтобы проверить, как это выглядит, до того как включить клиенту.
      </div>
      <div className="stack" style={{ gap: 8 }}>
        <div className="small muted">Кому</div>
        <div className="chips">
          {RECIPIENTS.map((r) => (
            <button
              key={r.value}
              className={`chip${settings.recipient === r.value ? " active" : ""}`}
              disabled={save.isPending}
              onClick={() => settings.recipient !== r.value && change({ recipient: r.value })}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {on && (
        <div className="stack" style={{ gap: 8 }}>
          <div className="small muted">Что отправлять</div>
          <div className="chips">
            {LEVELS.map((l) => (
              <button
                key={l.value}
                className={`chip${settings.level === l.value ? " active" : ""}`}
                disabled={save.isPending}
                onClick={() => settings.level !== l.value && change({ level: l.value })}
              >
                {l.label}
              </button>
            ))}
          </div>
          <div className="tiny faint">
            Важные: отмена, перезаказ, отправка, стоимость доставки, корректировка баланса, «требует внимания».
          </div>
        </div>
      )}
      {settings.recipient === "client" && !settings.client_has_telegram && (
        <div className="banner warning small">У клиента не указан Telegram ID — отправлять некому.</div>
      )}
      {on && !settings.bot_running && (
        <div className="banner warning small">
          Бот сейчас не запущен на сервере — уведомления уйдут, когда он заработает (если прошло меньше суток).
        </div>
      )}
      {on && settings.last_error && (
        <div className="banner negative small">
          Последняя отправка не удалась: {settings.last_error}
          {settings.last_error_at ? ` · ${dateTime(settings.last_error_at)}` : ""}
        </div>
      )}
      {on && settings.last_sent_at && !settings.last_error && (
        <div className="tiny faint">Последнее уведомление отправлено {dateTime(settings.last_sent_at)}</div>
      )}
      {on && (
        <div className="tiny faint">
          Получатель должен хотя бы раз открыть бота в личке и нажать «Start» — иначе Telegram не даёт боту
          написать первым.
        </div>
      )}
    </div>
  );
}

function SettingsPage({ onLeaveDemo }: { onLeaveDemo?: () => void }) {
  const toast = useToast();
  const settings = useSettings();
  const setRate = useSetRate();
  const [rate, setRateValue] = useState<number | null>(null);
  const current = settings.data?.krw_per_usd ?? null;
  return (
    <>
      <PageHead title="Настройки" />
      <div className="stack">
        <PinSettings />
        <div className="card pad stack">
          <h3>Курс KRW / USD</h3>
          <div className="small muted">
            Баланс в долларах = баланс в вонах ÷ курс. Сейчас:{" "}
            <b className="num">{current ? `1 $ = ${current.toLocaleString("en-US")} ₩` : "не задан"}</b>
            {settings.data?.updated_at ? ` · ${dateTime(settings.data.updated_at)}` : ""}
          </div>
          <div className="row">
            <div className="grow">
              <MoneyInput value={rate} onChange={setRateValue} placeholder={current ? String(current) : "1350"} />
            </div>
            <button
              className="btn primary"
              disabled={!rate || setRate.isPending}
              onClick={() =>
                setRate.mutate(rate!, {
                  onSuccess: () => {
                    toast("Курс обновлён");
                    setRateValue(null);
                  },
                  onError: (e) => toast(errorText(e), "error"),
                })
              }
            >
              Сохранить
            </button>
          </div>
        </div>
        {settings.data?.notifications && <NotificationsCard settings={settings.data.notifications} />}
        <div className="card pad stack">
          <h3>Фото</h3>
          <div className="small muted">
            {settings.data?.uploads_enabled
              ? "Загрузка фото включена: изображения сжимаются в WebP и хранятся отдельно от базы."
              : "Хранилище фото не настроено (FIREBASE_STORAGE_BUCKET)."}
          </div>
        </div>
        {onLeaveDemo && (
          <button className="btn ghost" onClick={onLeaveDemo}>
            Демо: сменить роль
          </button>
        )}
      </div>
    </>
  );
}

function AdminShipmentDetails() {
  const [editing, setEditing] = useState<Shipment | null>(null);
  return (
    <>
      <ShipmentDetailsPage
        onEdit={(shipment, orders) => (
          <div className="row" style={{ gap: 6 }}>
            <ShipmentSplitButton shipment={shipment} orders={orders} />
            <ShipmentDeliveredButton orders={orders} />
            <EditButton onClick={() => setEditing(shipment)} />
          </div>
        )}
      />
      {editing && <ShipmentEditSheet shipment={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

export function AdminApp({ onLeaveDemo }: { onLeaveDemo?: () => void }) {
  return (
    <Shell nav={NAV} title="Buyer CRM">
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/orders" element={<AdminOrdersPage />} />
        <Route path="/orders/new" element={<NewOrderPage />} />
        <Route path="/orders/:id" element={<OrderDetailsPage adminPanel={(order) => <OrderAdminPanel order={order} />} />} />
        <Route path="/shipments" element={<AdminShipmentsPage />} />
        <Route path="/shipments/:id" element={<AdminShipmentDetails />} />
        <Route path="/finance" element={<FinancePage />} />
        <Route path="/balance" element={<Navigate to="/finance" replace />} />
        <Route path="/settings" element={<SettingsPage onLeaveDemo={onLeaveDemo} />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
