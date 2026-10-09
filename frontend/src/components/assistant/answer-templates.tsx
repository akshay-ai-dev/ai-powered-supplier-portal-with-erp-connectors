// How the chat widget shows a tool's result, sized for the 384 px chat panel. No text generation: every value shown
// comes from the tool result as is (SRS §6.3). Four tools have their own layout, drafts get a confirm card, and the
// other tools a simple generic view.
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { money } from "@/lib/api";
import type { ChatDraft, ChatReply } from "@/lib/types";
import { StatusBadge } from "@/components/status-badge";
import { ConfirmCard } from "./confirm-card";
import { DraftAwardCard, type DraftAward } from "./draft-award-card";

export interface RequestRow {
  id: number;
  req_number: string;
  title: string;
  quantity: number;
  needed_by: string | null;
  erp: string;
  stage: string;
  quote_count: number;
  po_number: string | null;
}

export interface RankedResponse {
  rank: number;
  quote_id: number;
  supplier_name: string | null;
  unit_price: number;
  total_price: number;
  lead_time_days: number;
  promised_date: string | null;
  meets_need_by: boolean;
  status: string;
}

export interface Comparison {
  req_number: string;
  title: string;
  item_code: string | null;
  quantity: number;
  needed_by: string | null;
  erp: string;
  stage: string;
  rule: string;
  ranking: RankedResponse[];
}

export interface RequestDetail {
  req_number: string;
  title: string;
  description: string | null;
  item_code: string | null;
  quantity: number;
  target_price: number | null;
  needed_by: string | null;
  quote_deadline: string | null;
  erp: string;
  stage: string;
  po_number: string | null;
  delivery_status: string | null;
  invitations: { supplier_name: string; quoted: boolean; declined: boolean; decline_reason: string | null }[];
  responses: { supplier_name: string; unit_price: number; lead_time_days: number; status: string; created_at: string }[];
  threads: { supplier_name: string; total: number; unread: number; last_at: string }[];
  history: { action: string; detail: string | null; user_name: string | null; created_at: string }[];
  shipments: {
    shipment_no: string;
    status: string;
    carrier: string | null;
    tracking_no: string | null;
    arrived_at: string | null;
    inspected_at: string | null;
    rejection_reason: string | null;
    inspection_notes: string | null;
    quality: { label: string; passed: boolean | null }[];
  }[];
}

export const erpName = (erp: string) => (erp === "infor" ? "Infor LN" : erp.toUpperCase());
/** Dates like "2026-10-15" (need-by, delivery) are calendar days: read them as local dates, because new Date()
 *  treats them as UTC midnight and shows the previous day west of UTC. Timestamps are parsed as they are. */
const toDate = (d: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(d);
};
const day = (d: string | null) => (d ? toDate(d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—");
/** "Oct 7": compact date for the panel (the year is implied in a live procurement conversation). */
const short = (d: string | null) => (d ? toDate(d).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—");

/** One ask-box answer: the tool's own layout, a confirm card for drafts, or the generic view. */
export function AnswerView({ reply, onNavigate }: { reply: ChatReply; onNavigate?: () => void }) {
  if (reply.tool === null) return <HelpAnswer examples={reply.help ?? []} />;
  if (reply.error) return <ErrorAnswer message={reply.error} />;
  const result = reply.result;
  switch (reply.tool) {
    case "list_requests": {
      const status = reply.args?.status;
      return <RequestsAnswer rows={result as RequestRow[]} stages={typeof status === "string" && status ? [status] : []} onNavigate={onNavigate} />;
    }
    case "get_request_detail":
      return <RequestDetailAnswer data={result as RequestDetail} />;
    case "compare_responses":
      return <ComparisonAnswer data={result as Comparison} />;
    case "draft_award":
      return <DraftAwardCard draft={result as DraftAward} onNavigate={onNavigate} />;
  }
  if (result && typeof result === "object" && "confirm" in result) return <ConfirmCard tool={reply.tool} draft={result as ChatDraft} onNavigate={onNavigate} />;
  return <GenericAnswer value={result} />;
}

/** A bordered list with one divider between rows, the building block of every answer. */
function Rows({ children }: { children: React.ReactNode }) {
  return <div className="divide-y overflow-hidden rounded-md border">{children}</div>;
}

export function RequestsAnswer({ rows, stages, onNavigate }: { rows: RequestRow[]; stages: string[]; onNavigate?: () => void }) {
  const shown = rows; // list_requests already filtered by stage; `stages` only labels the answer
  return (
    <div className="space-y-2">
      <p>
        <b>{shown.length}</b> request{shown.length === 1 ? "" : "s"}
        {stages.length > 0 && <span className="text-muted-foreground"> · stage: {stages.join(", ")}</span>}
      </p>
      {shown.length === 0 ? (
        <p className="text-muted-foreground">No requests match.</p>
      ) : (
        <Rows>
          {shown.map((r) => (
            <Link key={r.req_number} href={`/requirements/${r.id}`} onClick={onNavigate} className="block px-3 py-2 hover:bg-accent/50">
              <div className="flex items-center gap-2">
                <span className="font-medium">{r.req_number}</span>
                <span className="min-w-0 flex-1 truncate">{r.title}</span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
                <StatusBadge status={r.stage} />
                <span>
                  {r.quote_count} quote{r.quote_count === 1 ? "" : "s"} · {erpName(r.erp)} · need {short(r.needed_by)}
                </span>
              </div>
            </Link>
          ))}
        </Rows>
      )}
    </div>
  );
}

/** The SRS ranking as stacked two-line rows (instead of a 6-column table): who and total, then price, delivery and on-time. */
export function RankingList({ ranking, highlight }: { ranking: RankedResponse[]; highlight?: number }) {
  return (
    <Rows>
      {ranking.map((r) => (
        <div key={r.quote_id} className={`px-3 py-2 ${r.quote_id === highlight ? "bg-accent/60" : ""}`}>
          <div className="flex items-baseline gap-2">
            <span className="w-10 shrink-0 font-medium">
              {r.quote_id === highlight ? "▶ " : ""}#{r.rank}
            </span>
            <span className="min-w-0 flex-1 truncate font-medium">{r.supplier_name}</span>
            <span className="font-medium tabular-nums">{money(r.total_price)}</span>
          </div>
          <div className="ml-12 text-xs text-muted-foreground">
            {money(r.unit_price)} each · {short(r.promised_date)} ·{" "}
            {r.meets_need_by ? <span className="text-emerald-700 dark:text-emerald-400">✓ on time</span> : <span className="text-destructive">✗ late</span>}
          </div>
        </div>
      ))}
    </Rows>
  );
}

export function ComparisonAnswer({ data }: { data: Comparison }) {
  return (
    <div className="space-y-2">
      <div>
        <div className="font-medium">
          {data.req_number} · {data.title}
        </div>
        <div className="text-xs text-muted-foreground">
          qty {data.quantity} · need by {day(data.needed_by)} · {erpName(data.erp)}
        </div>
      </div>
      {data.ranking.length === 0 ? <p className="text-muted-foreground">No responses yet.</p> : <RankingList ranking={data.ranking} />}
      <p className="text-xs text-muted-foreground">Rule: {data.rule}</p>
    </div>
  );
}

function Section({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      {empty ? <div className="text-muted-foreground">None</div> : <div className="space-y-0.5">{children}</div>}
    </div>
  );
}

export function RequestDetailAnswer({ data }: { data: RequestDetail }) {
  return (
    <div className="space-y-2.5 rounded-md border p-3">
      <div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">
            {data.req_number} · {data.title}
          </span>
          <StatusBadge status={data.stage} />
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Item {data.item_code ?? "—"} · qty {data.quantity} · need by {day(data.needed_by)}
          <br />
          {erpName(data.erp)} · PO {data.po_number ?? "—"} · deadline {day(data.quote_deadline)}
          {data.delivery_status && ` · ${data.delivery_status}`}
        </div>
      </div>
      <Section title={`Responses (${data.responses.length})`} empty={data.responses.length === 0}>
        {data.responses.map((r) => (
          <div key={r.supplier_name} className="flex flex-wrap items-center gap-1.5">
            <span>
              {r.supplier_name} {money(r.unit_price)} · {r.lead_time_days} d
            </span>
            <StatusBadge status={r.status} />
          </div>
        ))}
      </Section>
      <Section title="Invitations" empty={data.invitations.length === 0}>
        {data.invitations.map((i) => (
          <div key={i.supplier_name}>
            {i.supplier_name} · {i.declined ? `declined${i.decline_reason ? ` (${i.decline_reason})` : ""}` : i.quoted ? "responded" : "invited"}
          </div>
        ))}
      </Section>
      <Section title="Shipments" empty={data.shipments.length === 0}>
        {data.shipments.map((s) => (
          <div key={s.shipment_no}>
            <div className="flex flex-wrap items-center gap-1.5">
              <span>{s.shipment_no}</span>
              <StatusBadge status={s.status} />
              <span className="text-muted-foreground">
                {s.carrier ?? ""} {s.tracking_no ?? ""}
              </span>
            </div>
            {s.inspected_at && (
              <div className="text-xs text-muted-foreground">
                {s.quality.map((q) => `${q.label} ${q.passed ? "✓" : "✗"}`).join(" · ")}
                {s.rejection_reason && <div>Rejected: {s.rejection_reason}</div>}
                {s.inspection_notes && <div>Notes: {s.inspection_notes}</div>}
              </div>
            )}
          </div>
        ))}
      </Section>
      <Section title="Messages" empty={data.threads.length === 0}>
        {data.threads.map((t) => (
          <div key={t.supplier_name}>
            {t.supplier_name} · {t.total} message{t.total === 1 ? "" : "s"}
            {t.unread > 0 && ` · ${t.unread} unread`}
          </div>
        ))}
      </Section>
      <Section title="History (latest 3)" empty={data.history.length === 0}>
        {data.history.slice(0, 3).map((h, i) => (
          <div key={i} className="text-xs">
            {short(h.created_at)} · {h.action}
            {h.detail && <span className="text-muted-foreground"> ({h.detail})</span>}
            {h.user_name && <span className="text-muted-foreground"> by {h.user_name}</span>}
          </div>
        ))}
      </Section>
    </div>
  );
}

export function HelpAnswer({ examples }: { examples: string[] }) {
  return (
    <div className="space-y-1">
      <p>I could not match that to something I can look up or draft. Try for example, or pick an option below:</p>
      <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
        {examples.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  );
}

export function ErrorAnswer({ message }: { message: string }) {
  return <p className="text-destructive">{message}</p>;
}

const label = (key: string) => (key.charAt(0).toUpperCase() + key.slice(1)).replace(/_/g, " ");
type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => !!v && typeof v === "object" && !Array.isArray(v);

/** A value on one line: item lines as "6 × ITEM004", other lists as a count, nested records as "key value" pairs. */
function inline(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) {
    if (v.every((x) => isRec(x) && ("item_code" in x || "MATNR" in x || "item" in x)))
      return v
        .map((x) => {
          const r = x as Rec;
          const qty = r.quantity ?? r.quantity_shipped ?? r.MENGE ?? r.LFIMG ?? r.qty ?? r.expected ?? "";
          return `${qty} × ${r.item_code ?? r.MATNR ?? r.item}`;
        })
        .join(", ");
    if (v.length === 0) return "None";
    return v.every((x) => !isRec(x)) ? v.join(", ") : `${v.length} item${v.length === 1 ? "" : "s"}`;
  }
  if (isRec(v)) return Object.entries(v).map(([k, x]) => `${k} ${inline(x)}`).join(" · ");
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

function Fields({ rec }: { rec: Rec }) {
  return (
    <div className="space-y-0.5">
      {Object.entries(rec).map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3">
          <span className="shrink-0 text-muted-foreground">{label(k)}</span>
          <span className="min-w-0 break-words text-right">{inline(v)}</span>
        </div>
      ))}
    </div>
  );
}

/** Any other tool's result as it is: a list becomes one block per record (first 10), a record a list of fields with
 *  its lists of records (like ERP documents) shown as blocks underneath. */
export function GenericAnswer({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-muted-foreground">Nothing found.</p>;
    return (
      <div className="space-y-2">
        <p>
          <b>{value.length}</b> result{value.length === 1 ? "" : "s"}
          {value.length > 10 && <span className="text-muted-foreground"> · first 10 shown</span>}
        </p>
        <Rows>
          {value.slice(0, 10).map((v, i) => (
            <div key={i} className="px-3 py-2">
              {isRec(v) ? <Fields rec={v} /> : inline(v)}
            </div>
          ))}
        </Rows>
      </div>
    );
  }
  if (!isRec(value)) return <p>{inline(value)}</p>;
  const flat = Object.fromEntries(Object.entries(value).filter(([, v]) => !(Array.isArray(v) && v.some(isRec) && !inline(v).includes("×"))));
  const lists = Object.entries(value).filter(([k]) => !(k in flat)) as [string, Rec[]][];
  return (
    <div className="space-y-2 rounded-md border p-3">
      <Fields rec={flat} />
      {lists.map(([k, rows]) => (
        <div key={k}>
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label(k)} ({rows.length})
          </div>
          {rows.length === 0 ? (
            <div className="text-muted-foreground">None</div>
          ) : (
            rows.map((r, i) => (
              <div key={i} className="mt-1 rounded-md bg-muted/50 px-2 py-1 text-xs">
                <Fields rec={r} />
              </div>
            ))
          )}
        </div>
      ))}
    </div>
  );
}
