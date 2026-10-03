// Fixed answer layouts for the AI Assistant, one per tool. No text generation: the same question always gets
// the same layout, so buyers learn where to look (see docs/decisions.md). Every value shown comes from the tool result.
import Link from "next/link";
import { dateTime, money, shortDate } from "@/lib/api";
import { StatusBadge } from "@/components/status-badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

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

const erpName = (erp: string) => (erp === "infor" ? "Infor LN" : erp.toUpperCase());
const day = (d: string | null) => (d ? shortDate(d) : "—");

function Section({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h4>
      {empty ? <p className="text-sm text-muted-foreground">None</p> : children}
    </div>
  );
}

function Facts({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
      {items.map(([k, v]) => (
        <div key={k}>
          <dt className="text-xs text-muted-foreground">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RequestsAnswer({ rows, stages }: { rows: RequestRow[]; stages: string[] }) {
  const shown = stages.length ? rows.filter((r) => stages.includes(r.stage)) : rows;
  return (
    <div className="space-y-2">
      <p className="text-sm">
        <b>{shown.length}</b> request{shown.length === 1 ? "" : "s"}
        {stages.length > 0 && <span className="text-muted-foreground"> · stage: {stages.join(", ")}</span>}
      </p>
      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">No requests match.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Request</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead className="text-right">Quotes</TableHead>
              <TableHead>ERP</TableHead>
              <TableHead>Needed by</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => (
              <TableRow key={r.req_number}>
                <TableCell>
                  <Link href={`/requirements/${r.id}`} className="font-medium hover:underline">
                    {r.req_number}
                  </Link>
                </TableCell>
                <TableCell>{r.title}</TableCell>
                <TableCell>
                  <StatusBadge status={r.stage} />
                </TableCell>
                <TableCell className="text-right">{r.quote_count}</TableCell>
                <TableCell>{erpName(r.erp)}</TableCell>
                <TableCell>{day(r.needed_by)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

export function RankingTable({ ranking, highlight }: { ranking: RankedResponse[]; highlight?: number }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Rank</TableHead>
          <TableHead>Supplier</TableHead>
          <TableHead className="text-right">Unit price</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead>Delivery</TableHead>
          <TableHead>Meets date</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {ranking.map((r) => (
          <TableRow key={r.quote_id} className={r.quote_id === highlight ? "bg-accent/50 font-medium" : ""}>
            <TableCell>
              {r.rank}
              {r.quote_id === highlight && " ▶"}
            </TableCell>
            <TableCell>{r.supplier_name}</TableCell>
            <TableCell className="text-right">{money(r.unit_price)}</TableCell>
            <TableCell className="text-right">{money(r.total_price)}</TableCell>
            <TableCell>{day(r.promised_date)}</TableCell>
            <TableCell>{r.meets_need_by ? "✓" : "✗"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ComparisonAnswer({ data }: { data: Comparison }) {
  return (
    <div className="space-y-2">
      <p className="text-sm">
        <b>{data.req_number}</b> · {data.title} · qty {data.quantity} · needed by {day(data.needed_by)} · {erpName(data.erp)}
      </p>
      {data.ranking.length === 0 ? <p className="text-sm text-muted-foreground">No responses yet.</p> : <RankingTable ranking={data.ranking} />}
      <p className="text-xs text-muted-foreground">Ranking rule: {data.rule}</p>
    </div>
  );
}

export function RequestDetailAnswer({ data }: { data: RequestDetail }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <b>{data.req_number}</b> · {data.title} <StatusBadge status={data.stage} />
      </div>
      <Facts
        items={[
          ["Item", data.item_code ?? "—"],
          ["Quantity", data.quantity],
          ["Needed by", day(data.needed_by)],
          ["ERP", erpName(data.erp)],
          ["Quote deadline", data.quote_deadline ? dateTime(data.quote_deadline) : "—"],
          ["Target price", data.target_price != null ? money(data.target_price) : "—"],
          ["PO", data.po_number ?? "—"],
          ["Delivery", data.delivery_status ?? "—"],
        ]}
      />
      <Section title="Invitations" empty={data.invitations.length === 0}>
        <ul className="space-y-0.5 text-sm">
          {data.invitations.map((i) => (
            <li key={i.supplier_name}>
              {i.supplier_name} · {i.declined ? `declined${i.decline_reason ? ` (${i.decline_reason})` : ""}` : i.quoted ? "responded" : "invited"}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Responses" empty={data.responses.length === 0}>
        <ul className="space-y-0.5 text-sm">
          {data.responses.map((r) => (
            <li key={r.supplier_name}>
              {r.supplier_name} · {money(r.unit_price)} each · {r.lead_time_days} days · <StatusBadge status={r.status} />
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Shipments and inspection" empty={data.shipments.length === 0}>
        <ul className="space-y-2 text-sm">
          {data.shipments.map((s) => (
            <li key={s.shipment_no}>
              <div>
                {s.shipment_no} · <StatusBadge status={s.status} /> · {s.carrier ?? "—"} {s.tracking_no ?? ""}
              </div>
              {s.inspected_at && (
                <div className="text-muted-foreground">
                  Checks: {s.quality.map((q) => `${q.label} ${q.passed ? "✓" : "✗"}`).join(" · ")}
                  {s.rejection_reason && <div>Rejected: {s.rejection_reason}</div>}
                  {s.inspection_notes && <div>Notes: {s.inspection_notes}</div>}
                </div>
              )}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Message threads" empty={data.threads.length === 0}>
        <ul className="space-y-0.5 text-sm">
          {data.threads.map((t) => (
            <li key={t.supplier_name}>
              {t.supplier_name} · {t.total} message{t.total === 1 ? "" : "s"}
              {t.unread > 0 && ` · ${t.unread} unread`}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="History (latest 5)" empty={data.history.length === 0}>
        <ul className="space-y-0.5 text-sm">
          {data.history.slice(0, 5).map((h, i) => (
            <li key={i}>
              {dateTime(h.created_at)} · {h.action}
              {h.detail && <span className="text-muted-foreground"> ({h.detail})</span>}
              {h.user_name && <span className="text-muted-foreground"> by {h.user_name}</span>}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

export function HelpAnswer() {
  return (
    <div className="space-y-1 text-sm">
      <p>I can answer four kinds of questions:</p>
      <ul className="list-disc pl-5 text-muted-foreground">
        <li>List requests, e.g. &quot;Which requests are waiting for an award?&quot;</li>
        <li>Show one request, e.g. &quot;Show REQ2001&quot;</li>
        <li>Compare responses, e.g. &quot;Compare the responses for REQ2001&quot;</li>
        <li>Draft an award, e.g. &quot;Award REQ2001 to the top-ranked supplier&quot;</li>
      </ul>
    </div>
  );
}

export function MissingRequestAnswer() {
  return <p className="text-sm">Which request? Add its number, for example REQ2001.</p>;
}

export function ErrorAnswer({ message }: { message: string }) {
  return <p className="text-sm text-destructive">{message}</p>;
}
