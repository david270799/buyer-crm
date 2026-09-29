import { AlertTriangle, MessageSquare, Plus, Search, Tag, Trash2, Truck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useOrders } from "../api/hooks";
import type { Order, OrderFilters } from "../api/types";
import { PageHead } from "../components/Layout";
import { OrderCard, Thumb } from "../components/orders";
import { StatusBadge } from "../components/status";
import { Checkbox, Empty, ErrorState, Loading, useDebounced, useLongPress, useSelection } from "../components/ui";
import { krw, plural, shortDate } from "../lib/format";
import { StatusChips, useOrderFilters } from "../shared/filters";
import { AttentionSheet, BulkStatusSheet, CommentSheet, DeleteConfirm, ShipmentSheet } from "./sheets";

type Bulk = "status" | "ship" | "comment" | "attention" | "delete" | null;
const PAGE = 50;

function OrderRow({ order, selection }: { order: Order; selection: ReturnType<typeof useSelection> }) {
  const navigate = useNavigate();
  const selected = selection.has(order.id);
  const press = useLongPress(
    () => {
      if (!selected) selection.toggle(order.id);
    },
    () => (selection.selected.length ? selection.toggle(order.id) : navigate(`/orders/${order.id}`)),
  );
  return (
    <tr className={`${selected ? "selected" : ""} no-callout`} {...press}>
      <td onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
        <Checkbox checked={selected} label={`Выбрать ${order.id}`} onChange={() => selection.toggle(order.id)} />
      </td>
      <td>
        <Thumb src={order.thumbnail_url ?? order.photo_url} alt={order.id} />
      </td>
      <td className="num" style={{ fontWeight: 600 }}>
        {order.id}
        {order.attention_required && <AlertTriangle size={13} style={{ marginLeft: 6, verticalAlign: -1, color: "var(--warning)" }} />}
      </td>
      <td>
        <div style={{ fontWeight: 500 }}>{order.brand ?? "—"}</div>
        <div className="small muted">{order.model ?? ""}</div>
      </td>
      <td>{order.size ?? "—"}</td>
      <td>
        <StatusBadge status={order.status} />
      </td>
      <td className="r">{krw(order.purchase_price)}</td>
      <td className="r">{krw(order.client_price)}</td>
      <td className={`r ${order.profit != null && order.profit < 0 ? "negative" : ""}`}>{krw(order.profit)}</td>
      <td className="small">{order.shipment_id ?? <span className="faint">—</span>}</td>
      <td className="small muted">{shortDate(order.timestamps.created_at ?? order.timestamps.bought_at)}</td>
    </tr>
  );
}

function OrdersTable({ orders, selection }: { orders: Order[]; selection: ReturnType<typeof useSelection> }) {
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
            <th />
            <th>Заказ</th>
            <th>Бренд / модель</th>
            <th>Размер</th>
            <th>Статус</th>
            <th className="r">Закупка</th>
            <th className="r">Клиенту</th>
            <th className="r">Прибыль</th>
            <th>Отправка</th>
            <th>Дата</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow key={order.id} order={order} selection={selection} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdminOrdersPage() {
  const filters = useOrderFilters();
  const q = useDebounced(filters.q);
  const [sort, setSort] = useState<NonNullable<OrderFilters["sort"]>>("newest");
  const [limit, setLimit] = useState(PAGE);
  const selection = useSelection();
  const [bulk, setBulk] = useState<Bulk>(null);
  useEffect(() => {
    setLimit(PAGE);
  }, [filters.status, q, sort, filters.attention]);

  const { data, error, isLoading, isFetching, refetch } = useOrders({
    status: filters.status,
    q,
    attention: filters.attention || undefined,
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
      <PageHead
        title="Заказы"
        sub={data ? `${data.total} ${plural(data.total, "заказ", "заказа", "заказов")}` : undefined}
        action={
          <Link to="/orders/new" className="btn primary small">
            <Plus size={16} /> Новый
          </Link>
        }
      />
      <div className="stack">
        <div className="filters">
          <div className="search">
            <Search size={16} />
            <input
              className="input"
              placeholder="Поиск: номер, бренд, модель, трек, комментарий"
              value={filters.q}
              onChange={(e) => filters.update({ q: e.target.value })}
            />
          </div>
          <select className="select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Сортировка">
            <option value="newest">Сначала новые</option>
            <option value="oldest">Сначала старые</option>
            <option value="price_desc">Дороже</option>
            <option value="price_asc">Дешевле</option>
          </select>
        </div>
        <StatusChips value={filters.status} onChange={(s) => filters.update({ status: s || null })} />
        <button
          className={`chip ${filters.attention ? "active" : ""}`}
          style={{ alignSelf: "flex-start" }}
          onClick={() => filters.update({ attention: filters.attention ? null : "1" })}
        >
          <AlertTriangle size={12} style={{ verticalAlign: -1 }} /> Требуют внимания
        </button>
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
            <div className="only-desktop">
              <OrdersTable orders={data.items} selection={selection} />
            </div>
            <div className="only-mobile order-grid">
              {data.items.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  selectable
                  showCost
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
    </>
  );
}
