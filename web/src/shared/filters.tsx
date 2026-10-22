import { AlertTriangle, LayoutGrid, List, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { OrderFilters, OrderStatus } from "../api/types";
import { STATUS_FLOW, STATUS_PLURAL } from "../lib/format";

const RING_R = 30;
const RING_LEN = 2 * Math.PI * RING_R;

/** «Заказы в работе» (the owner, 22.10.2026): a ring with the total inside
 * and the stages in order next to it (Новые › Выкуплены › Склад › Карго).
 * «Доставлен» is left out: it only grows. A tap on a stage opens its orders. */
export function StatusPipeline({ counts }: { counts: Record<OrderStatus, number> }) {
  const navigate = useNavigate();
  const stages = STATUS_FLOW.filter((status) => status !== "delivered");
  const total = stages.reduce((sum, status) => sum + (counts[status] ?? 0), 0);
  let offset = 0;
  return (
    <div className="pipeline">
      <svg className="pipeline-ring" viewBox="0 0 76 76" aria-hidden="true">
        <circle cx="38" cy="38" r={RING_R} className="track" />
        {stages.map((status) => {
          const share = total ? ((counts[status] ?? 0) / total) * RING_LEN : 0;
          const gap = share > 3 ? 2 : 0;
          const arc = (
            <circle
              key={status}
              cx="38"
              cy="38"
              r={RING_R}
              className={`c-${status}`}
              strokeDasharray={`${Math.max(share - gap, 0)} ${RING_LEN}`}
              strokeDashoffset={-offset}
            />
          );
          offset += share;
          return share ? arc : null;
        })}
        <text x="38" y="38" className="total">
          {total}
        </text>
        <text x="38" y="52" className="caption">
          в работе
        </text>
      </svg>
      <div className="pipeline-chain">
        {stages.map((status) => (
          <button key={status} type="button" className={`c-${status}`} onClick={() => navigate(`/orders?status=${status}`)}>
            <i className="status-dot" />
            <span>{STATUS_PLURAL[status]}</span>
            <b className="num">{counts[status] ?? 0}</b>
          </button>
        ))}
      </div>
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

const FILTERS_KEY = "crm-order-filters";
// Kept across restarts (owner, 11.10): status, sort and «внимание»; the search text is not.
const KEPT = ["status", "sort", "attention"];
let restored = false; // restore once per app start; later a bare /orders means «cleared»

function readSaved(): URLSearchParams | null {
  try {
    const raw = localStorage.getItem(FILTERS_KEY);
    return raw ? new URLSearchParams(raw) : null;
  } catch {
    return null;
  }
}

export function useOrderFilters() {
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    if (!restored) {
      restored = true;
      const saved = readSaved();
      if (saved && !KEPT.some((k) => params.has(k)) && [...saved.keys()].length) {
        const merged = new URLSearchParams(params);
        saved.forEach((value, key) => merged.set(key, value));
        setParams(merged, { replace: true });
        return;
      }
    }
    const keep = new URLSearchParams();
    for (const key of KEPT) {
      const value = params.get(key);
      if (value) keep.set(key, value);
    }
    try {
      localStorage.setItem(FILTERS_KEY, keep.toString());
    } catch {
      /* storage unavailable */
    }
  }, [params, setParams]);
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
  const stuck = params.get("stuck") === "1";
  const problem = params.get("problem") === "1";
  return { status, attention, stuck, problem, q: params.get("q") ?? "", sort: params.get("sort") ?? "", update };
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

/** Search behind a magnifier button (owner, 10.10: the always-open field took
 * too much room). Stays open while there is a query. */
export function useSearchToggle(q: string): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(Boolean(q));
  return [open || Boolean(q), setOpen];
}

export function SearchButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={`btn icon-only search-toggle ${open ? "active" : ""}`}
      onClick={onToggle}
      aria-label="Поиск"
      title="Поиск"
    >
      <Search size={16} />
    </button>
  );
}

export function SearchField({
  value,
  onChange,
  onClose,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onClose: () => void;
  placeholder: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
  }, []);
  return (
    <div className="search search-open">
      <Search size={16} />
      <input ref={input} className="input" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
      <button
        type="button"
        className="btn icon-only small search-close"
        onClick={() => {
          onChange("");
          onClose();
        }}
        aria-label="Закрыть поиск"
      >
        <X size={16} />
      </button>
    </div>
  );
}

/** «Требуют внимания» as an icon next to the magnifier (owner, 10.10). */
export function AttentionButton({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={`btn icon-only attention-toggle ${active ? "active" : ""}`}
      onClick={onToggle}
      aria-pressed={active}
      aria-label="Требуют внимания"
      title="Требуют внимания"
    >
      <AlertTriangle size={16} />
    </button>
  );
}
