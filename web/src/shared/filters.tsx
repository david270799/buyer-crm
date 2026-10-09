import { LayoutGrid, List } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { OrderFilters, OrderStatus } from "../api/types";
import { StatusIcon } from "../components/status";
import { STATUS_FLOW, STATUS_PLURAL } from "../lib/format";

export function StatusTiles({ counts }: { counts: Record<OrderStatus, number> }) {
  const navigate = useNavigate();
  return (
    <div className="tiles">
      {STATUS_FLOW.map((status) => (
        <button key={status} className="tile" onClick={() => navigate(`/orders?status=${status}`)}>
          <span className="count">{counts[status] ?? 0}</span>
          <span className="name">
            <StatusIcon status={status} size={14} />
            {STATUS_PLURAL[status]}
          </span>
        </button>
      ))}
    </div>
  );
}

export function StatusChips({ value, onChange }: { value: OrderStatus | ""; onChange: (v: OrderStatus | "") => void }) {
  const options: (OrderStatus | "")[] = ["", ...STATUS_FLOW, "cancelled"];
  return (
    <div className="chips" role="tablist">
      {options.map((status) => (
        <button
          key={status || "all"}
          role="tab"
          aria-selected={value === status}
          className={`chip ${status ? `c-${status}` : ""} ${value === status ? "active" : ""}`}
          onClick={() => onChange(status)}
        >
          {status && <span className="status-dot" />}
          {status ? STATUS_PLURAL[status] : "Все"}
        </button>
      ))}
    </div>
  );
}

export function useOrderFilters() {
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") ?? "") as OrderStatus | "";
  const attention = params.get("attention") === "1";
  const update = (next: Record<string, string | null>) => {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value) merged.set(key, value);
      else merged.delete(key);
    }
    setParams(merged, { replace: true });
  };
  return { status, attention, q: params.get("q") ?? "", sort: params.get("sort") ?? "", update };
}

export type OrderSort = NonNullable<OrderFilters["sort"]>;

/** Sort kept in the URL like the filters (survives opening an order and coming back). */
export function useOrderSort(filters: ReturnType<typeof useOrderFilters>): [OrderSort, (v: OrderSort) => void] {
  const sort = (filters.sort || "newest") as OrderSort;
  return [sort, (value) => filters.update({ sort: value === "newest" ? null : value })];
}

export function SortSelect({ value, onChange }: { value: OrderSort; onChange: (v: OrderSort) => void }) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value as OrderSort)} aria-label="Сортировка">
      <option value="newest">Сначала новые</option>
      <option value="oldest">Сначала старые</option>
      <option value="price_desc">Дороже</option>
      <option value="price_asc">Дешевле</option>
      <option value="status">По статусу</option>
    </select>
  );
}

export type OrdersView = "cards" | "list";

const VIEW_KEY = "crm-orders-view";

/** «Карточки» or «Список», remembered on this phone. Default: cards on a
 * phone, the table on a wide screen. */
export function useOrdersView(): [OrdersView, (v: OrdersView) => void] {
  const [view, setView] = useState<OrdersView>(() => {
    try {
      const saved = localStorage.getItem(VIEW_KEY);
      if (saved === "cards" || saved === "list") return saved;
    } catch {
      /* storage unavailable */
    }
    return window.matchMedia?.("(min-width: 960px)").matches ? "list" : "cards";
  });
  const set = (v: OrdersView) => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* storage unavailable */
    }
  };
  return [view, set];
}

export function ViewToggle({ value, onChange }: { value: OrdersView; onChange: (v: OrdersView) => void }) {
  return (
    <div className="view-toggle" role="group" aria-label="Вид">
      <button className={`btn icon-only ${value === "cards" ? "active" : ""}`} onClick={() => onChange("cards")} aria-label="Карточки" title="Карточки">
        <LayoutGrid size={16} />
      </button>
      <button className={`btn icon-only ${value === "list" ? "active" : ""}`} onClick={() => onChange("list")} aria-label="Список" title="Список">
        <List size={16} />
      </button>
    </div>
  );
}
