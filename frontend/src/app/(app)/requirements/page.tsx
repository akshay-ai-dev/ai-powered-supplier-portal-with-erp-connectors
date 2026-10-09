"use client";
import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { Requirement } from "@/lib/types";
import { buttonVariants } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { AgentBadge } from "@/components/agent-badge";

const STAGES = ["", "Open", "Quoted", "Quotes closed", "Awarded", "In Transit", "Delivered", "Rejected", "Closed", "Cancelled"];

export default function RequirementsPage() {
  const { user } = useAuth();
  const isSupplier = user?.role === "supplier";
  const isAdmin = user?.role === "admin";
  const isBuyer = user?.role === "buyer";
  const shouldWrap = isSupplier || isBuyer || isAdmin;
  const canWrite = user?.role === "buyer" || user?.role === "admin";
  const columnCount = isAdmin ? 9 : isSupplier || isBuyer ? 8 : 7;
  const wrapText = (text: string) => shouldWrap
    ? text.split("\n").map((line) => line.match(/.{1,20}/gu)?.join("\n") ?? "").join("\n")
    : text;
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
        <Table className={`min-w-[1000px] ${shouldWrap ? "[&_td]:whitespace-pre-wrap" : ""}`}>
          <TableHeader>
            <TableRow>
              <TableHead>Requirement</TableHead>
              {isAdmin && <TableHead>Buyer name</TableHead>}
              {(isAdmin || isSupplier || isBuyer) && <TableHead>Supplier name</TableHead>}
              <TableHead>Quantity</TableHead>
              <TableHead>Ship date</TableHead>
              <TableHead>Carrier</TableHead>
              <TableHead>Tracking number</TableHead>
              <TableHead>Lot numbers</TableHead>
              <TableHead>Serial numbers</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={columnCount} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={columnCount} className="text-center text-muted-foreground">
                  Nothing here yet.
                </TableCell>
              </TableRow>
            )}
            {data?.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="align-top">
                  <Link href={`/requirements/${r.id}`} className="font-medium underline-offset-4 hover:underline">
                    {wrapText(r.title)}
                  </Link>
                  <div className="text-xs text-muted-foreground">{wrapText(r.req_number)}</div>
                  {isSupplier && r.buyer_name && <div className="text-xs text-muted-foreground">{wrapText(r.buyer_name)}</div>}
                  <span className="mt-1 inline-block"><AgentBadge channel={r.created_via} compact /></span>
                  {r.unread_messages > 0 && (
                    <span className="ml-2 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground">{r.unread_messages} new</span>
                  )}
                </TableCell>
                {isAdmin && <TableCell className="align-top">{wrapText(r.buyer_name || "—")}</TableCell>}
                {isAdmin && <TableCell className="align-top">{wrapText(["Closed", "Awarded", "In Transit"].includes(r.stage) ? r.supplier_name || "—" : "—")}</TableCell>}
                {(isSupplier || isBuyer) && <TableCell className="align-top">{wrapText(r.supplier_name || "—")}</TableCell>}
                <TableCell className="align-top">{r.quantity}</TableCell>
                <TableCell className="align-top">{r.ship_date || "—"}</TableCell>
                <TableCell className="align-top">{wrapText(r.carrier || "—")}</TableCell>
                <TableCell className="max-w-48 whitespace-pre-wrap break-all align-top">{wrapText(r.tracking_number || "—")}</TableCell>
                <TableCell className="max-w-48 whitespace-pre-wrap break-words align-top">{wrapText(r.lot_numbers || "—")}</TableCell>
                <TableCell className="max-w-48 whitespace-pre-wrap break-words align-top">{wrapText(r.serial_numbers || "—")}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
