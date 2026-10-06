"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ScanLine } from "lucide-react";
import { Suspense, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { dateTime, tzMinutes } from "@/lib/api";
import type { Shipment } from "@/lib/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { QrScanner } from "@/components/qr-scanner";

const STATUSES = ["", "Shipped", "Arrived", "Approved", "Rejected"];
const VIEWS: Record<string, string> = {
  arriving_today: "shipments expected today that have not arrived",
  overdue: "overdue shipments: expected before today, not arrived",
  inspected_today: "shipments inspected today",
};

export default function ShipmentsPage() {
  // useSearchParams needs a Suspense boundary so the page can still be prerendered
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <Shipments />
    </Suspense>
  );
}

function Shipments() {
  const { user } = useAuth();
  const params = useSearchParams();
  const router = useRouter();
  const wantedStatus = params?.get("status") ?? ""; // the dashboards link here with ?status=Shipped
  const [status, setStatus] = useState(STATUSES.includes(wantedStatus) ? wantedStatus : "");
  const wantedView = params?.get("view") ?? ""; // ...or with ?view=arriving_today
  const view = Object.hasOwn(VIEWS, wantedView) ? wantedView : "";
  const { data, error, loading } = useFetch<Shipment[]>(`/api/shipments?status=${status}${view ? `&view=${view}&tz=${tzMinutes()}` : ""}`);
  const inspector = user?.role === "inspector" || user?.role === "admin";

  return (
    <>
      <PageHeader
        title={inspector ? "Receiving" : "Shipments"}
        description={inspector ? "Incoming shipments to receive and inspect." : user?.role === "supplier" ? "Your shipments and their inspection results." : "Shipments against your purchase orders."}
      >
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || "All statuses"}
            </option>
          ))}
        </select>
      </PageHeader>
      <ErrorNote message={error} />
      {view && (
        <p className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="rounded-full bg-accent px-3 py-1">Showing {VIEWS[view]}</span>
          <button className="text-xs text-muted-foreground underline" onClick={() => router.replace("/shipments")}>
            Show all shipments
          </button>
        </p>
      )}
      <div className="mb-4 max-w-xl">
        <div className="mb-1 flex items-center gap-1 text-xs font-medium uppercase text-muted-foreground">
          <ScanLine className="size-3" /> Find a unit by its QR code
        </div>
        <QrScanner onScan={(code) => router.push(`/units/${encodeURIComponent(code)}`)} placeholder="Scan or type a unit code" />
      </div>
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Shipment</TableHead>
              <TableHead>PO</TableHead>
              {user?.role !== "supplier" && <TableHead className="hidden sm:table-cell">Supplier</TableHead>}
              <TableHead>Status</TableHead>
              <TableHead className="hidden md:table-cell">Tracking</TableHead>
              <TableHead className="hidden md:table-cell">ERP</TableHead>
              <TableHead className="hidden lg:table-cell">Submitted</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  No shipments.
                </TableCell>
              </TableRow>
            )}
            {data?.map((s) => (
              <TableRow key={s.id}>
                <TableCell>
                  <Link href={`/shipments/${s.id}`} className="font-medium underline-offset-4 hover:underline">
                    {s.shipment_no}
                  </Link>
                </TableCell>
                <TableCell>{s.po_number}</TableCell>
                {user?.role !== "supplier" && <TableCell className="hidden sm:table-cell">{s.supplier_name}</TableCell>}
                <TableCell>
                  <StatusBadge status={s.status} />
                </TableCell>
                <TableCell className="hidden md:table-cell">{s.tracking_no || "—"}</TableCell>
                <TableCell className="hidden uppercase md:table-cell">{s.erp}</TableCell>
                <TableCell className="hidden lg:table-cell">{dateTime(s.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
