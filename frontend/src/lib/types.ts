export type Role = "buyer" | "supplier" | "admin" | "inspector";
export type POStatus = "Draft" | "Pending" | "Approved" | "Closed";
export type DeliveryStatus = "Not Shipped" | "In Transit" | "Delivered" | "Rejected";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  supplier_id: number | null;
  owner_id?: number | null;
  owner_name?: string | null; // an inspector created by a buyer: that buyer
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
  /** Portal path the bell opens on click, e.g. "/requirements/7". Null for older notifications. */
  link: string | null;
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
  items: { item_code: string; quantity_shipped: number; quantity_received: number | null; quantity_accepted?: number | null }[];
  unit_level?: boolean;
  unit_counts?: Record<string, number>;
  override_reason?: string;
  replaces_shipment_id?: number | null; // the earlier shipment whose faulty, missing or rejected units this one replaces
  replaces_shipment_no?: string | null;
  replaced_by?: { id: number; shipment_no: string; status: Shipment["status"] }[];
  owed?: { item_code: string; quantity: number }[]; // units of this shipment that still need replacing
  packing_list: ShipmentFile | null;
  photos: ShipmentFile[];
  quality: { key: string; label: string; passed: boolean | null }[];
  improvement_request: string;
  // The supplier's reviewed packing-list draft, stored in full (null for shipments made without one).
  packing_list_review?: {
    ship_date: string | null;
    carrier: string | null;
    shipped_quantity: number | null;
    unit_of_measure: string | null;
    tracking_numbers: string[];
    lot_numbers: string[];
    serial_numbers: string[];
  } | null;
}
export interface InspectorDashboard {
  role: "inspector";
  incoming: number;
  awaiting_inspection: number;
  approved: number;
  rejected: number;
  notifications: Notification[];
}

// ---- Unit-by-unit inspection (QR-coded units, inspector-defined test fields, lot report)
export type UnitStatus = "Shipped" | "Received" | "OK" | "Faulty" | "Missing";
export type FieldType = "pass_fail" | "number" | "text";
export interface TestField {
  id: number;
  label: string;
  type: FieldType;
  unit_label: string;
  min_value: number | null;
  max_value: number | null;
  required: boolean;
  item_code: string | null;
  tolerance?: string;
}
export type FieldResult = "pass" | "fail" | null;
export interface UnitBrief {
  code: string;
  item_code: string;
  seq: number;
  status: UnitStatus;
  defect_type: string;
  defect_label: string;
  notes: string;
  tested_at: string | null;
  readings: Record<string, string | number>;
  field_results: Record<string, FieldResult>;
}
export interface UnitList {
  total: number;
  counts: Record<string, number>;
  offset: number;
  limit: number;
  units: UnitBrief[];
  fields: TestField[];
  items: string[];
  shipment_status: string;
}
export interface UnitFull extends UnitBrief {
  checks: { key: string; label: string; passed: boolean | null }[];
  field_values: { field_id: number; label: string; type: FieldType; unit_label: string; tolerance: string; required: boolean; archived: boolean; value: string | number | null; result: FieldResult }[];
  photos: ShipmentFile[];
  history: { action: string; detail: string; channel: string; created_at: string; user_name: string | null }[];
  received_by: string | null;
  received_at: string | null;
  tested_by: string | null;
  shipment: { id: number; shipment_no: string; status: string; po_number: string; supplier_name: string | null; erp: string };
  can_test: boolean;
  can_receive: boolean;
}
export interface LotReport {
  shipment_no: string;
  status: string;
  frozen: boolean;
  totals: { shipped: number; received: number; missing: number; tested: number; untested: number; ok: number; faulty: number };
  quality_accuracy: number | null;
  fulfilment_accuracy: number | null;
  threshold: number;
  suggestion: "approve" | "reject" | null;
  per_item: { item_code: string; shipped: number; received: number; ok: number; faulty: number; missing: number }[];
  defects: { defect_type: string; label: string; count: number }[];
  failed_checks: { key: string; label: string; count: number }[];
  fields: { id: number; label: string; type: FieldType; unit_label: string; required: boolean; tolerance: string; units: number; recorded: number; not_recorded: number; passed: number; failed: number; min?: number; max?: number; average?: number }[];
  faulty_units: { code: string; item_code: string; defect_type: string; defect_label: string; notes: string; failed_checks: string[]; failed_fields: { label: string; value: string | number; unit_label: string; tolerance: string }[] }[];
  blockers: string[];
  ready: boolean;
  decision: "approve" | "reject" | null;
  decided_at: string | null;
  decided_by: string | null;
  override_reason: string;
  replacement?: ReplacementLinks; // read live, not part of the frozen report
}
/** One line of what an inspected shipment still owes: faulty, missing or rejected units less what replacements covered. */
export interface OwedLine {
  item_code: string;
  short: number;
  replaced: number;
  on_the_way: number;
  outstanding: number;
}
export interface UnitToReplace {
  code: string;
  item_code: string;
  status: "Faulty" | "Missing";
  defect_label: string;
  notes: string;
}
export interface ReplacementLinks {
  replaces: { id: number; shipment_no: string; status: string; items: OwedLine[]; units: UnitToReplace[] } | null;
  replaced_by: { id: number; shipment_no: string; status: Shipment["status"]; shipped: number; accepted: number | null; quality_accuracy: number | null }[];
  owed: OwedLine[];
}
/** GET /api/purchase-orders/{id}/to-ship */
export interface ToShip {
  progress: { item_code: string; ordered: number; accepted: number; on_the_way: number; left: number }[];
  replace: { shipment_id: number; shipment_no: string; status: "Approved" | "Rejected"; decided_at: string | null; items: OwedLine[]; units: UnitToReplace[] }[];
}
export interface LabelData {
  shipment_no: string;
  po_number: string;
  supplier_name: string | null;
  base_url: string;
  units: { code: string; item_code: string; seq: number }[];
}

export const DEFECT_OPTIONS: Record<string, string> = {
  dimensional: "Dimensional problem",
  cosmetic: "Cosmetic damage",
  functional: "Functional failure",
  wrong_item: "Wrong item",
  missing_parts: "Missing parts",
  packaging: "Packaging damage",
  documentation: "Documentation problem",
  out_of_tolerance: "Measurement out of tolerance",
  other: "Other",
};

/** An inspector a buyer created: they see and inspect only that buyer's shipments. */
export interface TeamInspector {
  id: number;
  name: string;
  email: string;
  role: "inspector";
  active: boolean;
  created_at: string;
  last_login: string | null;
  inspected: number;
}

// ---- Chat assistant (numbered menus + "Fill this form with AI"; /api/assistant/*)
export interface AssistantOption {
  key: string;
  label: string;
  description?: string;
}
export interface AssistantControls {
  back: boolean;
  cancel: boolean;
  skip: boolean;
  more: boolean;
  file: boolean;
  confirm?: boolean;
}
export interface AssistantResult {
  label: string;
  href: string;
  upload?: string;
}
export interface AssistantResponse {
  stage: "menu" | "step" | "summary";
  state: Record<string, unknown> | null;
  message: string;
  error: string | null;
  options: AssistantOption[];
  controls: AssistantControls;
  kind?: "text" | "int" | "number" | "date" | "datetime" | "choice" | "multichoice" | "file";
  hint?: string;
  title?: string;
  filter?: string;
  summary?: { label: string; value: string }[];
  warning?: string;
  progress?: { done: number; total: number };
  result: AssistantResult | null;
}

/** A draft tool's result: what would be saved and the REST call that saves it. Nothing is saved until the user confirms. */
export interface ChatDraft {
  saved: false;
  summary: Record<string, string | number>;
  confirm: { method: string; path: string; body: unknown; label: string };
}
/** One answer from the ask box (POST /api/assistant/chat): the one MCP tool GPT-4o picked, its arguments and its result as is. */
export interface ChatReply {
  tool: string | null;
  args?: Record<string, unknown>;
  result?: unknown;
  error?: string;
  help?: string[];
}

/** A field-level note on an extracted packing-list draft. A review aid from the model, not verified proof. */
export interface FieldIssue {
  field: string;
  severity: "review" | "warning" | "info";
  code: string;
  message: string;
}

/** The reviewable draft returned by POST /api/extraction-prefill/shipments/{po_id}. Saves nothing. */
export interface ExtractionDraft {
  ship_date: string | null;
  carrier: string | null;
  tracking_numbers: string[];
  shipped_quantity: number | null;
  unit_of_measure: string | null;
  lot_numbers: string[];
  serial_numbers: string[];
  items: { item_number: string | null; description: string | null; quantity_ordered: number | null; quantity_shipped: number | null; quantity_backordered: number | null; unit_of_measure: string | null }[];
  references: { value: string; label: string | null; page: number | null; kind: string }[];
  evidence: { field: string; page: number | null; text: string }[];
  field_issues: FieldIssue[];
}

/** One requested item in a buyer requirement draft. Used to let the buyer choose when a document
 * lists several items; quantities of different items are never combined. */
export interface RequirementDraftItem {
  item_name: string | null;
  specs: string | null;
  quantity: number | null;
  unit_of_measure: string | null;
  target_price: number | null;
}

/** The reviewable buyer draft returned by POST /api/extraction-prefill/requirements. Saves nothing:
 * no requirement, attachment or ERP call. The ERP system is not extracted; the buyer selects it. */
export interface RequirementDraft {
  title: string | null;
  description: string | null;
  quantity: number | null;
  target_price: number | null;
  needed_by: string | null;
  quote_deadline: string | null;
  quote_deadline_tz?: string | null;
  items: RequirementDraftItem[];
  references: { value: string; label: string | null; page: number | null; kind: string }[];
  evidence: { field: string; page: number | null; text: string }[];
  field_issues: FieldIssue[];
}

/** Result of comparing a reviewed shipped quantity against the PO (POST …/shipments/{po_id}/compare). */
export interface QuantityComparison {
  status: "match" | "over_shipped" | "under_shipped" | "cannot_compare";
  reason: string;
  item_code: string | null;
  po_quantity: number | null;
  shipped_quantity: number | null;
  difference: number | null;
  unit_note: string;
}
