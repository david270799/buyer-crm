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
  client_comment: string | null;
  attention_required: boolean;
  timestamps: Record<string, string>;
  // Admin only
  source_url?: string | null;
  purchase_price?: number | null;
  profit?: number | null;
  charged_amount_krw?: number;
  internal_comment?: string | null;
  purchases?: Purchase[];
  rebuy_count?: number;
  recognition?: Recognition | null;
  source_chat_id?: number | null;
  source_message_id?: number | null;
}

/** What Gemini read from the client's photo (admin only). */
export interface Recognition {
  engine: string | null;
  recognized: boolean;
  brand: string | null;
  model: string | null;
  category: string | null;
  size: string | null;
  confidence: number | null;
  error: string | null;
}

export interface Purchase {
  purchase_price: number | null;
  client_price: number | null;
  source_url: string | null;
  bought_at: string | null;
  replaced_at?: string | null;
  note?: string | null;
}

export type EventType =
  | "order_created"
  | "order_bought"
  | "order_rebought"
  | "order_cancelled"
  | "order_warehouse"
  | "order_delivered"
  | "order_status"
  | "order_discount"
  | "comment"
  | "attention"
  | "shipment_sent"
  | "shipment_updated"
  | "shipping_cost"
  | "deposit"
  | "adjustment"
  | "rate";

export interface CrmEvent {
  id: string;
  type: EventType | null;
  important: boolean;
  title: string;
  body: string | null;
  order_ids: string[];
  shipment_id: string | null;
  amount_krw: number | null;
  created_at: string | null;
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
  /** All photos; the first is also photo_url / thumbnail_url. */
  photos?: { photo_url: string; thumbnail_url: string | null }[];
  order_ids: string[];
  order_count: number;
  comment: string | null;
  created_at: string | null;
  /** Every order delivered → «Доставлена», otherwise «В пути». */
  delivered?: boolean;
  // Admin only
  shipping_charged_krw?: number;
}

export type LedgerType =
  | "order_charge"
  | "order_refund"
  | "order_rebuy"
  | "deposit"
  | "adjustment"
  | "shipping_charge"
  | "order_discount";

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

export interface PhotoRecognition {
  recognized: boolean;
  brand: string | null;
  model: string | null;
  size: string | null;
  category: string | null;
  confidence: number;
  not_a_product: boolean;
}

export interface LinkImport {
  brand: string | null;
  model: string | null;
  category: string | null;
  title: string | null;
  photo_url: string | null;
  thumbnail_url: string | null;
  engine: string | null;
  /** What did not work (no photo, Gemini unsure...). */
  note: string | null;
}

export interface DeletePreview {
  orders: Order[];
  refund_krw: number;
  not_found: string[];
  skipped: { order_id: string; reason: string }[];
}

export interface DeleteResult {
  deleted: string[];
  not_found: string[];
  skipped: { order_id: string; reason: string }[];
  refunded_krw: number;
  change: BalanceChange | null;
  next_order_id: string | null;
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
  /** The admin looks at the client's view («Как видит клиент»). */
  preview?: boolean;
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

export type NotifyRecipient = "off" | "admins" | "client";
export type NotifyLevel = "important" | "all";

export interface NotificationSettings {
  recipient: NotifyRecipient;
  level: NotifyLevel;
  updated_at: string | null;
  last_sent_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  client_has_telegram: boolean;
  bot_running: boolean;
}
