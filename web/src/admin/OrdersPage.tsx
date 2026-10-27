import { AlertTriangle, ChevronRight, Hourglass, MessageSquare, Percent, Plus, Tag, Trash2, Truck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useOrders, useOverview } from "../api/hooks";
import type { Order } from "../api/types";
import { OrderCard, Photo, Thumb } from "../components/orders";
import { StatusBadge } from "../components/status";
import { Checkbox, Empty, ErrorState, Loading, useDebounced, useLongPress, useSelection } from "../components/ui";
import { krw, orderTitle, plural, shortDate, sizeText } from "../lib/format";
import {
  AttentionButton,
  SearchButton,
  SearchField,
  SortSelect,
  StatusChips,
  useOrderFilters,
  useOrderSort,
  useOrdersView,
  useSearchToggle,
  ViewToggle,
} from "../shared/filters";
import { OrderAdminPanel } from "./OrderAdminPanel";
import { AttentionSheet, BulkStatusSheet, CommentSheet, DeleteConfirm, DiscountSheet, ShipmentSheet } from "./sheets";

type Bulk = "status" | "ship" | "comment" | "attention" | "discount" | "delete" | null;
const PAGE = 50;

function OrderRow({
  order,
  selection,
  previewed,
  onPreview,
}: {
  order: Order;
  selection: ReturnType<typeof useSelection>;
  previewed: boolean;
  onPreview: (id: string) => void;
}) {
  const navigate = useNavigate();
  const selected = selection.has(order.id);
  // A click shows the order in the panel on the right (the owner, 27.10.2026);
  // a double click opens the full page.
  const press = useLongPress(
    () => {
      if (!selected) selection.toggle(order.id);
    },
    () => (selection.selected.length ? selection.toggle(order.id) : onPreview(order.id)),
  );
  return (
    <tr
      className={`${selected ? "selected" : ""} ${previewed ? "previewed" : ""} no-callout`}
      {...press}
      onDoubleClick={() => navigate(`/orders/${order.id}`)}
    >
      <td onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
        <Checkbox checked={selected} label={`Выбрать ${order.id}`} onChange={() => selection.toggle(order.id)} />
      </td>
      <td className="col-thumb">
        <Thumb src={order.thumbnail_url ?? order.photo_url} alt={order.id} />
      </td>
      <td className="num" style={{ fontWeight: 600 }}>
        {order.id}
        {order.attention_required && <AlertTriangle size={13} style={{ marginLeft: 6, verticalAlign: -1, color: "var(--warning)" }} />}
        {order.stuck_days != null && (
          <div className="badge stuck" style={{ marginTop: 4 }} title={`Не пришёл на склад${order.shop ? ` · ${order.shop}` : ""}`}>
            <Hourglass size={11} /> {order.stuck_days} дн.{order.shop ? ` · ${order.shop}` : ""}
          </div>
        )}
      </td>
      <td className="col-name">
        <div style={{ fontWeight: 500 }}>{order.brand ?? "—"}</div>
        <div className="small muted">
          {order.model ?? ""}
          {/* Size moves here when the panel on the right takes the room. */}
          <span className="split-size">{sizeText(order) ? ` · ${sizeText(order)}` : ""}</span>
        </div>
      </td>
      <td className="nowrap col-size">{sizeText(order) ?? "—"}</td>
      <td>
        <StatusBadge status={order.status} />
      </td>
      <td className="r col-buy">{krw(order.purchase_price)}</td>
      <td className="r">{krw(order.client_price)}</td>
      <td className={`r ${order.profit != null && order.profit < 0 ? "negative" : ""}`}>{krw(order.profit)}</td>
      <td className="small col-wide nowrap">{order.shipment_id ?? <span className="faint">—</span>}</td>
      <td className="small muted col-wide nowrap">{shortDate(order.timestamps.created_at ?? order.timestamps.bought_at)}</td>
    </tr>
  );
}

function OrdersTable({
  orders,
  selection,
  preview,
  onPreview,
}: {
  orders: Order[];
  selection: ReturnType<typeof useSelection>;
  preview: string | null;
  onPreview: (id: string) => void;
}) {
  const allSelected = orders.length > 0 && orders.every((o) => selection.has(o.id));
  return (
    <div className="card table-wrap">
      <table className="orders">
        <thead>
          <tr>
            <th style={{ width: 40 }}>
              <Checkbox
                checked={allSelected}
                label="Выбрать все"
                onChange={() => selection.set(allSelected ? [] : orders.map((o) => o.id))}
              />
            </th>
            <th className="col-thumb" />
            <th>Заказ</th>
            <th>Бренд / модель</th>
            <th className="col-size">Размер</th>
            <th>Статус</th>
            <th className="r col-buy">Закупка</th>
            <th className="r">Клиенту</th>
            <th className="r">Прибыль</th>
            <th className="col-wide">Отправка</th>
            <th className="col-wide">Дата</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow key={order.id} order={order} selection={selection} previewed={order.id === preview} onPreview={onPreview} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Wide screen «Заказы» (variant 1, the owner, 27.10.2026): the table, and the
 * clicked order on the right with its prices and actions. */
function OrdersSplit({
  orders,
  selection,
  preview,
  onPreview,
  onClose,
}: {
  orders: Order[];
  selection: ReturnType<typeof useSelection>;
  preview: string | null;
  onPreview: (id: string) => void;
  onClose: () => void;
}) {
  const order = preview ? orders.find((o) => o.id === preview) : undefined;
  return (
    <div className={order ? "orders-split" : ""}>
      <OrdersTable orders={orders} selection={selection} preview={order ? preview : null} onPreview={onPreview} />
      {order && <OrderPreview order={order} onClose={onClose} />}
    </div>
  );
}

function OrderPreview({ order, onClose }: { order: Order; onClose: () => void }) {
  const size = sizeText(order);
  return (
    <aside className="order-preview" key={order.id}>
      <div className="card pad stack">
        <div className="row between">
          <span className="cap">Заказ {order.id}</span>
          <button className="btn small ghost icon-only" onClick={onClose} aria-label="Закрыть" title="Закрыть">
            <X size={16} />
          </button>
        </div>
        <Photo src={order.photo_url ?? order.thumbnail_url} alt={orderTitle(order)} />
        <div className="row between" style={{ alignItems: "flex-start" }}>
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="preview-title">{orderTitle(order)}</div>
            <div className="small muted">{[order.brand, size && `размер ${size}`].filter(Boolean).join(" · ")}</div>
          </div>
          <StatusBadge status={order.status} />
        </div>
        {order.client_comment && <div className="small">💬 {order.client_comment}</div>}
        <Link to={`/orders/${order.id}`} className="btn block">
          Открыть заказ <ChevronRight size={16} />
        </Link>
      </div>
      <OrderAdminPanel order={order} />
    </aside>
  );
}

export function AdminOrdersPage() {
  const filters = useOrderFilters();
  const [view, setView] = useOrdersView();
  const q = useDebounced(filters.q);
  const [sort, setSort] = useOrderSort(filters);
  const [searching, setSearching] = useSearchToggle(filters.q);
  const [limit, setLimit] = useState(PAGE);
  const selection = useSelection();
  const [bulk, setBulk] = useState<Bulk>(null);
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    setLimit(PAGE);
  }, [filters.status, q, sort, filters.attention, filters.stuck, filters.problem]);

  const { data, error, isLoading, isFetching, refetch } = useOrders({
    status: filters.status,
    q,
    attention: filters.attention || undefined,
    stuck: filters.stuck || undefined,
    problem: filters.problem || undefined,
    sort,
    limit,
  });
  const done = () => {
    setBulk(null);
    selection.clear();
  };
  const ids = selection.selected;

  return (
    <>
      {/* No heading (the owner, 22.10.2026): the list starts at the top; «+» sits in the toolbar. */}
      <div className="stack">
        <div className="filters">
          <SortSelect value={sort} onChange={setSort} />
          <ViewToggle value={view} onChange={setView} />
          <Link to="/orders/new" className="btn primary icon-only" aria-label="Новый заказ" title="Новый заказ">
            <Plus size={18} />
          </Link>
          <SearchButton open={searching} onToggle={() => setSearching(!searching)} />
          <AttentionButton
            active={filters.attention}
            onToggle={() => filters.update({ attention: filters.attention ? null : "1" })}
          />
        </div>
        {searching && (
          <SearchField
            value={filters.q}
            onChange={(q) => filters.update({ q })}
            onClose={() => setSearching(false)}
            placeholder="Поиск: номер, бренд, модель, трек, комментарий"
          />
        )}
        <StatusChips value={filters.status} onChange={(s) => filters.update({ status: s || null })} />
        {filters.problem && (
          <button type="button" className="stuck-banner active" onClick={() => filters.update({ problem: null })}>
            <AlertTriangle size={16} />
            <span className="grow">Показаны заказы, требующие внимания</span>
            <b>Сбросить</b>
          </button>
        )}
        <StuckBanner
          active={filters.stuck}
          onToggle={() => filters.update(filters.stuck ? { stuck: null } : { stuck: "1", status: null })}
        />
      </div>

      <div className="section">
        {isLoading ? (
          <Loading rows={6} height={56} />
        ) : error || !data ? (
          <ErrorState error={error} onRetry={refetch} />
        ) : !data.items.length ? (
          <Empty title="Ничего не найдено" />
        ) : (
          <>
            {view === "list" && (
              <div className="only-desktop">
                <OrdersSplit
                  orders={data.items}
                  selection={selection}
                  preview={preview}
                  onPreview={(id) => setPreview(id === preview ? null : id)}
                  onClose={() => setPreview(null)}
                />
              </div>
            )}
            <div className={view === "list" ? "only-mobile order-rows card" : "order-grid"}>
              {data.items.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  selectable
                  showCost
                  compact={view === "list"}
                  selected={selection.has(order.id)}
                  selecting={ids.length > 0}
                  onToggle={() => selection.toggle(order.id)}
                />
              ))}
            </div>
            {data.total > data.items.length && (
              <button className="btn block" style={{ marginTop: 14 }} disabled={isFetching} onClick={() => setLimit(limit + PAGE)}>
                {isFetching ? "Загрузка…" : `Показать ещё (${data.total - data.items.length})`}
              </button>
            )}
          </>
        )}
      </div>

      {ids.length > 0 && (
        <div className="selection-bar" role="toolbar" aria-label="Действия с выбранными">
          <b className="num" style={{ whiteSpace: "nowrap" }}>
            {ids.length}
          </b>
          {/* Actions scroll sideways: there is room for more of them. */}
          <div className="selection-actions">
            <button className="btn" onClick={() => setBulk("status")}>
              <Tag size={16} /> Статус
            </button>
            <button className="btn" onClick={() => setBulk("ship")}>
              <Truck size={16} /> Отправка
            </button>
            <button className="btn" onClick={() => setBulk("comment")}>
              <MessageSquare size={16} />
              <span>
                Коммент<i className="long">арий</i>
              </span>
            </button>
            <button className="btn" onClick={() => setBulk("attention")}>
              <AlertTriangle size={16} /> Внимание
            </button>
            <button className="btn" onClick={() => setBulk("discount")}>
              <Percent size={16} /> Скидка
            </button>
            <button className="btn" onClick={() => setBulk("delete")}>
              <Trash2 size={16} /> Удалить
            </button>
          </div>
          <button className="btn icon-only" onClick={selection.clear} aria-label="Снять выбор">
            <X size={16} />
          </button>
        </div>
      )}
      {bulk === "status" && <BulkStatusSheet ids={ids} onClose={() => setBulk(null)} onDone={done} />}
      {bulk === "ship" && <ShipmentSheet ids={ids} onClose={() => setBulk(null)} onDone={done} />}
      {bulk === "comment" && <CommentSheet ids={ids} onClose={() => setBulk(null)} onDone={done} />}
      {bulk === "attention" && <AttentionSheet ids={ids} onClose={() => setBulk(null)} onDone={done} />}
      {bulk === "delete" && <DeleteConfirm ids={ids} onClose={() => setBulk(null)} onDone={done} />}
      {bulk === "discount" && (
        <DiscountSheet
          orders={(data?.items ?? []).filter((o) => ids.includes(o.id))}
          onClose={() => setBulk(null)}
          onDone={done}
        />
      )}
    </>
  );
}

/** The dashboard's one orange line (the owner, 22.10.2026): «внимание» and
 * orders stuck before the warehouse together; a tap shows exactly those. */
export function ProblemBanner() {
  const { data } = useOverview();
  const count = data?.orders.problem_count ?? 0;
  if (!count) return null;
  return (
    <Link to="/orders?problem=1" className="stuck-banner">
      <AlertTriangle size={16} />
      <span className="grow">
        {count} {plural(count, "заказ требует", "заказа требуют", "заказов требуют")} внимания
      </span>
      <ChevronRight size={18} />
    </Link>
  );
}

/** «Не пришли на склад»: bought 4+ days ago and still «Выкуплен» (owner, 16.10). */
export function StuckBanner({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  const { data } = useOverview();
  const count = data?.orders.stuck_count ?? 0;
  if (!count && !active) return null;
  return (
    <button type="button" className={`stuck-banner ${active ? "active" : ""}`} onClick={onToggle}>
      <Hourglass size={16} />
      <span className="grow">
        {active
          ? "Показаны заказы, не пришедшие на склад"
          : `${count} ${plural(count, "заказ не пришёл", "заказа не пришли", "заказов не пришли")} на склад за 4 дня`}
      </span>
      <b>{active ? "Сбросить" : "Показать"}</b>
    </button>
  );
}
