export type Role = "buyer" | "supplier" | "admin" | "inspector";
export type POStatus = "Draft" | "Pending" | "Approved" | "Closed";
export type DeliveryStatus = "Not Shipped" | "In Transit" | "Delivered" | "Rejected";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  supplier_id: number | null;
}
export interface Supplier {
  id: number;
  supplier_name: string;
  email: string;
  phone: string;
  address: string;
  created_at: string;
}
export interface InventoryItem {
  id: number;
  item_code: string;
  description: string;
  stock_quantity: number;
  warehouse: string;
  source: string;
  created_by: number | null;
  can_edit?: boolean;
  can_delete?: boolean;
  in_use?: number;
  updated_at: string;
}
export interface POItem {
  item_code: string;
  quantity: number;
  unit_price: number;
}
export interface PurchaseOrder {
  id: number;
  po_number: string;
  supplier_id: number;
  supplier_name: string;
  status: POStatus;
  delivery_status: DeliveryStatus;
  total_amount: number;
  erp_reference: string | null;
  invoice_hold?: number;
  invoice_hold_reason?: string;
  requirement_id?: number | null;
  created_via: string;
  created_at: string;
  items: POItem[];
  history?: import("@/components/agent-badge").HistoryEntry[];
}
export interface Notification {
  id: number;
  title: string;
  message: string;
  is_read: number;
  created_at: string;
}
export interface BuyerDashboard {
  role: "buyer";
  open_orders: number;
  inventory_count: number;
  low_stock_count: number;
  supplier_count: number;
  orders_by_status: Record<string, number>;
  spend_by_supplier: { name: string; total: number }[];
  recent_activity: { action: string; entity_id: string; detail: string; channel: string; created_at: string; user_name: string | null }[];
}
export interface AdminDashboard {
  role: "admin";
  users_by_role: Record<string, number>;
  suppliers: number;
  inventory_items: number;
  requirements_by_status: Record<string, number>;
  orders_by_status: Record<string, number>;
  recent_audit: { action: string; entity: string; entity_id: string; detail: string; channel: string; created_at: string; user_name: string | null }[];
}
export interface SupplierDashboard {
  role: "supplier";
  active_orders: number;
  pending_deliveries: number;
  notifications: Notification[];
}

export type Stage = "Open" | "Quoted" | "Quotes closed" | "Awarded" | "In Transit" | "Delivered" | "Rejected" | "Closed" | "Cancelled";
export interface Quote {
  id: number;
  supplier_id: number;
  supplier_name?: string;
  unit_price: number;
  lead_time_days: number;
  message: string;
  status: "Submitted" | "Accepted" | "Rejected" | "Withdrawn";
  created_at: string;
}
export interface Requirement {
  id: number;
  req_number: string;
  title: string;
  description: string;
  item_code: string | null;
  quantity: number;
  target_price: number | null;
  needed_by: string | null;
  status: "Open" | "Awarded" | "Cancelled";
  erp: "sap" | "infor";
  open_to_all: number;
  quote_deadline: string | null;
  quotes_closed: boolean;
  unread_messages: number;
  my_decline?: { reason: string } | null;
  threads?: { supplier_id: number; supplier_name: string; total: number; unread: number; last_at: string }[];
  stage: Stage;
  po_id: number | null;
  po_number: string | null;
  delivery_status: string | null;
  quote_count: number;
  created_via: string;
  created_at: string;
  history?: import("@/components/agent-badge").HistoryEntry[];
  quotes?: Quote[];
  invites?: { supplier_id: number; supplier_name: string; quoted: boolean; declined: boolean; decline_reason: string }[];
  attachments?: Attachment[];
  my_quote?: Quote | null;
  awarded_to_me?: boolean;
}

export interface Attachment {
  id: number;
  filename: string;
  size: number;
  created_at: string;
}

export interface ShipmentFile {
  id: number;
  kind: "packing_list" | "photo";
  filename: string;
  size: number;
  created_at: string;
}
export interface Shipment {
  id: number;
  shipment_no: string;
  po_id: number;
  po_number: string;
  supplier_id: number;
  supplier_name: string | null;
  erp: string;
  carrier: string;
  tracking_no: string;
  expected_arrival: string | null;
  notes: string;
  status: "Shipped" | "Arrived" | "Approved" | "Rejected";
  erp_inbound_ref: string | null;
  erp_movement_ref: string | null;
  arrived_at: string | null;
  inspected_at: string | null;
  inspection_notes: string;
  rejection_reason: string;
  created_at: string;
  items: { item_code: string; quantity_shipped: number; quantity_received: number | null }[];
  packing_list: ShipmentFile | null;
  photos: ShipmentFile[];
  quality: { key: string; label: string; passed: boolean | null }[];
  improvement_request: string;
}
export interface InspectorDashboard {
  role: "inspector";
  incoming: number;
  awaiting_inspection: number;
  approved: number;
  rejected: number;
  notifications: Notification[];
}
