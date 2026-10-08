// Fixed answer layouts for the buyer assistant, one per tool, sized for the 384 px chat panel. No text generation:
// the same question always gets the same layout, so buyers learn where to look (see docs/decisions.md). Every value
// shown comes from the tool result.
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { api, money } from "@/lib/api";
import { extractReqNumber, extractStages, type Route } from "@/lib/router/classify";
import { StatusBadge } from "@/components/status-badge";
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

export type Answer =
  | { kind: "list_requests"; data: RequestRow[]; stages: string[] }
  | { kind: "get_request_detail"; data: RequestDetail }
  | { kind: "compare_responses"; data: Comparison }
  | { kind: "draft_award"; data: DraftAward }
  | { kind: "help" }
  | { kind: "missing" }
  | { kind: "error"; message: string };

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

/** Calls the tool the router picked (its REST copy, POST /api/mcp/<tool>, with the buyer's login) and returns the answer to render. */
export async function answerFor(text: string, tool: Route): Promise<Answer> {
  if (tool === "none") return { kind: "help" };
  if (tool === "list_requests") return { kind: tool, data: await api<RequestRow[]>("/api/mcp/list_requests", { body: {} }), stages: extractStages(text) };
  const req_number = extractReqNumber(text);
  if (!req_number) return { kind: "missing" };
  const data = await api(`/api/mcp/${tool}`, { body: { req_number } });
  return { kind: tool, data } as Answer;
}

export function AnswerView({ answer, onNavigate }: { answer: Answer; onNavigate?: () => void }) {
  switch (answer.kind) {
    case "list_requests":
      return <RequestsAnswer rows={answer.data} stages={answer.stages} onNavigate={onNavigate} />;
    case "get_request_detail":
      return <RequestDetailAnswer data={answer.data} />;
    case "compare_responses":
      return <ComparisonAnswer data={answer.data} />;
    case "draft_award":
      return <DraftAwardCard draft={answer.data} onNavigate={onNavigate} />;
    case "help":
      return <HelpAnswer />;
    case "missing":
      return <MissingRequestAnswer />;
    case "error":
      return <ErrorAnswer message={answer.message} />;
  }
}

/** A bordered list with one divider between rows, the building block of every answer. */
function Rows({ children }: { children: React.ReactNode }) {
  return <div className="divide-y overflow-hidden rounded-md border">{children}</div>;
}

export function RequestsAnswer({ rows, stages, onNavigate }: { rows: RequestRow[]; stages: string[]; onNavigate?: () => void }) {
  const shown = stages.length ? rows.filter((r) => stages.includes(r.stage)) : rows;
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

export function HelpAnswer() {
  return (
    <div className="space-y-1">
      <p>I can answer four kinds of questions, or pick an option below:</p>
      <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
        <li>Which requests are waiting for an award?</li>
        <li>Show REQ2001</li>
        <li>Compare the responses for REQ2001</li>
        <li>Award REQ2001 to the top-ranked supplier</li>
      </ul>
    </div>
  );
}

export function MissingRequestAnswer() {
  return <p>Which request? Add its number, for example REQ2001.</p>;
}

export function ErrorAnswer({ message }: { message: string }) {
  return <p className="text-destructive">{message}</p>;
}
