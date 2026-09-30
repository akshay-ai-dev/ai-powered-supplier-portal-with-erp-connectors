"use client";
import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { deadlineLabel, money, shortDate } from "@/lib/api";
import type { Requirement } from "@/lib/types";
import { buttonVariants } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { AgentBadge } from "@/components/agent-badge";

const STAGES = ["", "Open", "Quoted", "Quotes closed", "Awarded", "In Transit", "Delivered", "Rejected", "Closed", "Cancelled"];

export default function RequirementsPage() {
  const { user } = useAuth();
  const isSupplier = user?.role === "supplier";
  const canWrite = user?.role === "buyer" || user?.role === "admin";
  const [stage, setStage] = useState("");
  const [tab, setTab] = useState<"all" | "mine">("all");
  const { data, error, loading } = useFetch<Requirement[]>(`/api/requirements?stage=${stage}&mine=${tab === "mine"}`);

  return (
    <>
      <PageHeader
        title="Requirements"
        description={isSupplier ? "Open buyer requirements you can quote on, and your applications." : user?.role === "inspector" ? "Every requirement and its quotes (read-only)." : "Post what you need, compare supplier quotes, and track delivery."}
      >
        {isSupplier && (
          <div className="inline-flex rounded-md border p-0.5 text-sm">
            {(["all", "mine"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`rounded px-3 py-1 ${tab === t ? "bg-accent font-medium" : "text-muted-foreground"}`}>
                {t === "all" ? "Open + mine" : "My applications"}
              </button>
            ))}
          </div>
        )}
        <select aria-label="Filter by stage" value={stage} onChange={(e) => setStage(e.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s || "All stages"}
            </option>
          ))}
        </select>
        {canWrite && (
          <Link href="/requirements/new" className={buttonVariants()}>
            <Plus className="mr-1 size-4" />
            New requirement
          </Link>
        )}
      </PageHeader>
      <ErrorNote message={error} />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Requirement</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="hidden sm:table-cell text-right">Target price</TableHead>
              <TableHead className="hidden lg:table-cell">ERP</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead className="hidden md:table-cell">{isSupplier ? "My quote" : "Quotes"}</TableHead>
              <TableHead className="hidden md:table-cell">Quote deadline</TableHead>
              <TableHead className="hidden lg:table-cell">Needed by</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground">
                  Nothing here yet.
                </TableCell>
              </TableRow>
            )}
            {data?.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link href={`/requirements/${r.id}`} className="font-medium underline-offset-4 hover:underline">
                    {r.title}
                  </Link>
                  <span className="ml-2"><AgentBadge channel={r.created_via} compact /></span>
                  {r.unread_messages > 0 && (
                    <span className="ml-2 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground">{r.unread_messages} new</span>
                  )}
                  <div className="text-xs text-muted-foreground">{r.req_number}</div>
                </TableCell>
                <TableCell className="text-right">{r.quantity}</TableCell>
                <TableCell className="hidden text-right sm:table-cell">{r.target_price != null ? money(r.target_price) : "—"}</TableCell>
                <TableCell className="hidden uppercase lg:table-cell">{r.erp}</TableCell>
                <TableCell>
                  <StatusBadge status={r.stage} />
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {isSupplier ? (r.my_quote ? `${money(r.my_quote.unit_price)} · ${r.my_quote.status}` : "Not applied") : r.quote_count}
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {r.status === "Open" && r.quote_deadline ? (
                    <span className={r.quotes_closed ? "text-orange-700 dark:text-orange-400" : ""} title={new Date(r.quote_deadline).toLocaleString()}>
                      {deadlineLabel(r.quote_deadline)}
                    </span>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell className="hidden lg:table-cell">{r.needed_by ? shortDate(r.needed_by) : "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
