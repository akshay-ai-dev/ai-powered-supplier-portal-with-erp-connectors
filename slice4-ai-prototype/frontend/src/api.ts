export type RequestSummary = {
  id: string;
  sourceErp: string;
  part: string;
  status: string;
  needByDate: string;
};

export type RankedOffer = {
  rank: number | null;
  supplierId: string;
  supplierName: string;
  currency: string;
  totalPrice: number;
  // Comparison value computed by the backend (converted when currencies differ).
  comparisonCurrency?: string | null;
  exchangeRateToComparison?: number | null;
  comparisonTotal?: number | null;
  promisedDate: string;
  meetsNeedBy: boolean;
};

export type ExchangeRate = {
  baseCurrency: string;
  ratesToBase: Record<string, number>;
  approved: boolean;
  source?: string | null;
  label?: string | null;
};

export type Comparison = {
  ranking?: RankedOffer[];
  rankingStatus?: 'ranked' | 'provisional_fx_ranking' | 'ranked_converted'
    | 'currency_review_required';
  rankingProvisional?: boolean;
  comparisonCurrency?: string | null;
  exchangeRate?: ExchangeRate | null;
  message?: string;
  status?: string;
  awardable?: boolean;
  awardBlockedReason?: string | null;
};
export type AwardDraft = {
  draft: boolean;
  status?: string;
  requestId?: string;
  message?: string;
  awardTo?: { supplierId: string; supplierName: string };
  rank?: number | null;
  justificationRequired?: boolean;
  justificationProvided?: string | null;
  justificationMissing?: boolean;
  justificationProblem?: string | null;
  rankingProvisional?: boolean;
  warnings?: string[];
  erpCallOnConfirm?: ErpCall;
};
// Proposed ERP action; shown to the buyer, never executed by this app.
export type ErpCall = {
  erp: string;
  operation: string;
  payload: {
    requisition: string;
    supplier: string;
    quantity: number;
    unitPrice: number;
    currency: string;
    deliveryDate: string;
  };
  idempotencyKey: string;
};
export type ChatReply = {
  answer: string;
  messages: Record<string, unknown>[];
  drafts?: { result: unknown }[];
};
// Fields marked optional were added later; the screen falls back when they are absent.
export type PrefillResult = {
  fields: Record<string, unknown>;
  unreadableFields: string[];
  manualEntryRequired?: { field: string; label: string; message: string }[];
  poQuantity: number | null;
  poQuantitySource?: 'manual_sample_input' | null;
  poQuantityNote?: string | null;
  quantityCheck?: { status: 'match' | 'mismatch' | 'not_checked'; message: string };
  quantityMismatch: boolean;
  note?: string;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const data: unknown = await response.json();
  if (!response.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === 'string' ? detail : 'Request failed');
  }
  return data as T;
}

export function jsonPost(data: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  };
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
