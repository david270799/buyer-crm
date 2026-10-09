import { useNavigate, useSearchParams } from "react-router-dom";

import type { OrderStatus } from "../api/types";
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
