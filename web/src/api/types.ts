export type Role = "admin" | "client";
export type OrderStatus = "new" | "bought" | "warehouse" | "cargo" | "delivered" | "cancelled";

export interface Order {
  id: string;
  status: OrderStatus | null;
  status_label: string | null;
  title: string | null;
  brand: string | null;
  model: string | null;
  size: string | null;
  client_price: number | null;
  cargo_code: string | null;
  shipment_id: string | null;
  photo_url: string | null;
  thumbnail_url: string | null;
  source_url: string | null;
  client_comment: string | null;
  attention_required: boolean;
  timestamps: Record<string, string>;
  // Admin only
  purchase_price?: number | null;
  profit?: number | null;
  charged_amount_krw?: number;
  internal_comment?: string | null;
}

export interface Shipment {
  id: string;
  shipment_number: number | null;
  tracking_code: string | null;
  box_number: string | null;
  weight_kg: number | null;
  shipping_cost_krw: number | null;
  shipment_date: string | null;
  photo_url: string | null;
  thumbnail_url: string | null;
  order_ids: string[];
  order_count: number;
  comment: string | null;
  created_at: string | null;
  // Admin only
  shipping_charged_krw?: number;
}

export type LedgerType = "order_charge" | "order_refund" | "deposit" | "adjustment" | "shipping_charge";

export interface LedgerItem {
  id: string;
  type: LedgerType | null;
  amount_krw: number;
  balance_before: number;
  balance_after: number;
  order_id: string | null;
  shipment_id: string | null;
  comment: string | null;
  created_at: string | null;
  order: { id: string; title: string | null; thumbnail_url: string | null } | null;
}

export interface Balance {
  krw: number;
  usd: number | null;
  krw_per_usd: number | null;
}

export interface Overview {
  balance: Balance;
  orders: {
    status_counts: Record<OrderStatus, number>;
    attention_count: number;
    total: number;
    active: number;
    profit_total_krw?: number | null;
    profit_month_krw?: number | null;
  };
  recent: Order[];
}

export interface BalanceChange {
  amount_krw: number;
  balance_before: number;
  balance_after: number;
}

export interface BulkResult {
  updated: string[];
  unchanged: string[];
  not_found: string[];
  skipped: { order_id: string; reason: string }[];
}

export interface ShipResult {
  shipment: Shipment | null;
  created: boolean;
  added: string[];
  already_in_shipment: string[];
  not_found: string[];
  skipped: { order_id: string; reason: string }[];
  change: BalanceChange | null;
}

export interface Me {
  role: Role;
  user: { id: number; first_name: string | null; username: string | null };
}

export interface OrdersPage {
  items: Order[];
  total: number;
}

export interface OrderFilters {
  status?: OrderStatus | "";
  q?: string;
  attention?: boolean;
  sort?: "newest" | "oldest" | "price_desc" | "price_asc";
  offset?: number;
  limit?: number;
}
