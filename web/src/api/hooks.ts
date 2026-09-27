import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, get, newIdempotencyKey, patch, post, put, query } from "./client";
import type {
  BalanceChange,
  BulkResult,
  LedgerItem,
  Me,
  Order,
  OrderFilters,
  OrdersPage,
  OrderStatus,
  Overview,
  Shipment,
  ShipResult,
} from "./types";

export const keys = {
  me: ["me"] as const,
  overview: ["overview"] as const,
  orders: (filters: OrderFilters) => ["orders", filters] as const,
  order: (id: string) => ["order", id] as const,
  shipments: ["shipments"] as const,
  shipment: (id: string) => ["shipment", id] as const,
  transactions: ["transactions"] as const,
  settings: ["settings"] as const,
};

export const useConfig = () =>
  useQuery({ queryKey: ["config"], queryFn: () => get<{ demo: boolean }>("/api/config") });

export const useMe = (enabled: boolean) =>
  useQuery({ queryKey: keys.me, queryFn: () => get<Me>("/api/me"), enabled, retry: false });

export const useOverview = () =>
  useQuery({ queryKey: keys.overview, queryFn: () => get<Overview>("/api/overview") });

export const useOrders = (filters: OrderFilters) =>
  useQuery({
    queryKey: keys.orders(filters),
    queryFn: () =>
      get<OrdersPage>(
        `/api/orders${query({
          status: filters.status,
          q: filters.q,
          attention: filters.attention,
          sort: filters.sort,
          offset: filters.offset,
          limit: filters.limit,
        })}`,
      ),
    placeholderData: (previous) => previous,
  });

export const useOrder = (id: string) =>
  useQuery({
    queryKey: keys.order(id),
    queryFn: () => get<{ order: Order; shipment: Shipment | null }>(`/api/orders/${encodeURIComponent(id)}`),
  });

export const useShipments = () =>
  useQuery({
    queryKey: keys.shipments,
    queryFn: () => get<{ items: Shipment[] }>("/api/shipments?limit=100"),
  });

export const useShipment = (id: string) =>
  useQuery({
    queryKey: keys.shipment(id),
    queryFn: () =>
      get<{ shipment: Shipment; orders: Order[] }>(`/api/shipments/${encodeURIComponent(id)}`),
  });

export const useTransactions = () =>
  useQuery({
    queryKey: keys.transactions,
    queryFn: () => get<{ items: LedgerItem[] }>("/api/transactions?limit=100"),
  });

export const useSettings = () =>
  useQuery({
    queryKey: keys.settings,
    queryFn: () =>
      get<{ krw_per_usd: number | null; updated_at: string | null; uploads_enabled: boolean }>(
        "/api/settings",
      ),
  });

// --- mutations ---------------------------------------------------------------

function useInvalidateAll() {
  const client = useQueryClient();
  // Every write can change the balance, counts and lists: refresh everything.
  return () => client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "config" && q.queryKey[0] !== "me" });
}

export interface NewOrderInput {
  brand?: string | null;
  model?: string | null;
  size?: string | null;
  source_url?: string | null;
  photo_url?: string | null;
  thumbnail_url?: string | null;
  purchase_price?: number | null;
  client_price?: number | null;
  client_comment?: string | null;
  internal_comment?: string | null;
  attention_required?: boolean;
  buy_now?: boolean;
}

export const useCreateOrder = () => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: NewOrderInput) =>
      post<{ order: Order; change: BalanceChange | null }>("/api/orders", body),
    onSuccess: refresh,
  });
};

export const useUpdateOrder = (id: string) => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: Partial<NewOrderInput>) => patch<{ order: Order }>(`/api/orders/${id}`, body),
    onSuccess: refresh,
  });
};

export const useBuy = (id: string) => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: { purchase_price: number; client_price: number }) =>
      post<{ order: Order; already_done: boolean; change: BalanceChange | null }>(
        `/api/orders/${id}/buy`,
        body,
      ),
    onSuccess: refresh,
  });
};

export const useCancel = (id: string) => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: () =>
      post<{ order: Order; already_done: boolean; refunded_krw: number; change: BalanceChange | null }>(
        `/api/orders/${id}/cancel`,
      ),
    onSuccess: refresh,
  });
};

export const useBulkStatus = () => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: { order_ids: string[]; status: OrderStatus }) =>
      post<BulkResult>("/api/orders/bulk/status", body),
    onSuccess: refresh,
  });
};

export const useBulkUpdate = () => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: {
      order_ids: string[];
      client_comment?: string | null;
      internal_comment?: string | null;
      attention_required?: boolean;
    }) => post<BulkResult>("/api/orders/bulk/update", body),
    onSuccess: refresh,
  });
};

export interface ShipmentInput {
  tracking_code?: string | null;
  box_number?: string | null;
  weight_kg?: number | null;
  shipping_cost_krw?: number | null;
  shipment_date?: string | null;
  comment?: string | null;
  photo_url?: string | null;
  thumbnail_url?: string | null;
}

export const useCreateShipment = () => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: ShipmentInput & { order_ids: string[] }) => post<ShipResult>("/api/shipments", body),
    onSuccess: refresh,
  });
};

export const useUpdateShipment = (id: string) => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: ShipmentInput) =>
      patch<{ shipment: Shipment; change: BalanceChange | null }>(`/api/shipments/${id}`, body),
    onSuccess: refresh,
  });
};

export const useMoney = (kind: "deposit" | "adjust") => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (body: { amount_krw: number; comment?: string | null; idempotency_key?: string }) =>
      post<{ entry: LedgerItem; already_done: boolean }>(`/api/finance/${kind}`, {
        ...body,
        idempotency_key: body.idempotency_key ?? newIdempotencyKey(),
      }),
    onSuccess: refresh,
  });
};

export const useSetRate = () => {
  const refresh = useInvalidateAll();
  return useMutation({
    mutationFn: (krw_per_usd: number) => put<{ krw_per_usd: number }>("/api/settings/rate", { krw_per_usd }),
    onSuccess: refresh,
  });
};

export async function uploadImage(file: File): Promise<{ photo_url: string; thumbnail_url: string }> {
  const form = new FormData();
  form.append("file", file);
  return api("/api/images", { method: "POST", body: form });
}
