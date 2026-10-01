"use client";
import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { dateTime } from "@/lib/api";
import type { Shipment } from "@/lib/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";

const STATUSES = ["", "Shipped", "Arrived", "Approved", "Rejected"];

export default function ShipmentsPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState("");
  const { data, error, loading } = useFetch<Shipment[]>(`/api/shipments?status=${status}`);
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
