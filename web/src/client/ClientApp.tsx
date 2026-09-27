import { AlertTriangle, Home, Package, Search, Truck, Wallet } from "lucide-react";
import { Link, Navigate, Route, Routes } from "react-router-dom";

import { useOrders, useOverview } from "../api/hooks";
import type { OrderFilters } from "../api/types";
import { type NavItem, PageHead, Shell } from "../components/Layout";
import { BalanceCard } from "../components/money";
import { OrderCard } from "../components/orders";
import { Empty, ErrorState, Loading, useDebounced } from "../components/ui";
import { plural } from "../lib/format";
import { BalancePage } from "../shared/BalancePage";
import { StatusChips, StatusTiles, useOrderFilters } from "../shared/filters";
import { NotificationsPage } from "../shared/NotificationsPage";
import { OrderDetailsPage } from "../shared/OrderDetailsPage";
import { ShipmentDetailsPage, ShipmentsPage } from "../shared/ShipmentsPages";

const NAV: NavItem[] = [
  { to: "/", label: "Главная", icon: Home },
  { to: "/orders", label: "Заказы", icon: Package },
  { to: "/shipments", label: "Отправки", icon: Truck },
  { to: "/balance", label: "Баланс", icon: Wallet },
];

function ClientHome() {
  const { data, error, isLoading, refetch } = useOverview();
  if (isLoading) return <Loading rows={3} height={110} />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  const attention = data.orders.attention_count;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <BalanceCard balance={data.balance} to="/balance" />
      {attention > 0 && (
        <Link to="/orders?attention=1" className="banner warning">
          <AlertTriangle size={18} />
          <div>
            {attention} {plural(attention, "заказ требует", "заказа требуют", "заказов требуют")} внимания
          </div>
        </Link>
      )}
      <StatusTiles counts={data.orders.status_counts} />
      <div className="section" style={{ marginTop: 8 }}>
        <div className="section-head">
          <h2>Заказы</h2>
          <Link to="/orders">Все {data.orders.total} →</Link>
        </div>
        {data.recent.length ? (
          <div className="order-grid">
            {data.recent.map((order) => (
              <OrderCard key={order.id} order={order} />
            ))}
          </div>
        ) : (
          <Empty title="Заказов пока нет" />
        )}
      </div>
    </div>
  );
}

function ClientOrders() {
  const filters = useOrderFilters();
  const q = useDebounced(filters.q);
  const request: OrderFilters = { status: filters.status, q, attention: filters.attention || undefined, limit: 200 };
  const { data, error, isLoading, refetch } = useOrders(request);
  return (
    <>
      <PageHead title="Заказы" sub={data ? `${data.total} ${plural(data.total, "заказ", "заказа", "заказов")}` : undefined} />
      <div className="stack">
        <div className="search">
          <Search size={16} />
          <input
            className="input"
            placeholder="Поиск: бренд, модель, номер, трек"
            value={filters.q}
            onChange={(e) => filters.update({ q: e.target.value })}
          />
        </div>
        <StatusChips value={filters.status} onChange={(s) => filters.update({ status: s || null, attention: null })} />
        {filters.attention && (
          <button className="chip active" style={{ alignSelf: "flex-start" }} onClick={() => filters.update({ attention: null })}>
            Требуют внимания ✕
          </button>
        )}
      </div>
      <div className="section">
        {isLoading ? (
          <Loading rows={4} height={200} />
        ) : error || !data ? (
          <ErrorState error={error} onRetry={refetch} />
        ) : !data.items.length ? (
          <Empty title="Ничего не найдено" hint="Попробуйте изменить фильтр или поиск." />
        ) : (
          <div className="order-grid">
            {data.items.map((order) => (
              <OrderCard key={order.id} order={order} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

export function ClientApp() {
  return (
    <Shell nav={NAV} title="Мои заказы">
      <Routes>
        <Route path="/" element={<ClientHome />} />
        <Route path="/orders" element={<ClientOrders />} />
        <Route path="/orders/:id" element={<OrderDetailsPage />} />
        <Route path="/shipments" element={<ShipmentsPage />} />
        <Route path="/shipments/:id" element={<ShipmentDetailsPage />} />
        <Route path="/balance" element={<BalancePage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
