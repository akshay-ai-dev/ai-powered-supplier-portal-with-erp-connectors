"use client";
import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { money, shortDate } from "@/lib/api";
import type { PurchaseOrder } from "@/lib/types";
import { buttonVariants } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { AgentBadge } from "@/components/agent-badge";

const STATUSES = ["", "Draft", "Pending", "Approved", "Closed"];

export default function PurchaseOrdersPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState("");
  const { data, error, loading } = useFetch<PurchaseOrder[]>(`/api/purchase-orders?status=${status}`);
  const isSupplier = user?.role === "supplier";
  const canWrite = user?.role === "buyer" || user?.role === "admin";

  return (
    <>
      <PageHeader title={isSupplier ? "My orders" : "Purchase orders"} description={isSupplier ? "Orders assigned to you." : user?.role === "inspector" ? "Every purchase order (read-only)." : "Track and manage purchase orders."}>
        <select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || "All statuses"}
            </option>
          ))}
        </select>
        {canWrite && (
          <Link href="/purchase-orders/new" className={buttonVariants()}>
            <Plus className="mr-1 size-4" />
            New PO
          </Link>
        )}
      </PageHeader>
      <ErrorNote message={error} />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>PO</TableHead>
              {!isSupplier && <TableHead>Supplier</TableHead>}
              <TableHead>Status</TableHead>
              <TableHead className="hidden sm:table-cell">Delivery</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="hidden md:table-cell">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  No purchase orders.
                </TableCell>
              </TableRow>
            )}
            {data?.map((po) => (
              <TableRow key={po.id}>
                <TableCell>
                  <Link className="font-medium underline-offset-4 hover:underline" href={`/purchase-orders/${po.id}`}>
                    {po.po_number}
                  </Link>
                  <span className="ml-2"><AgentBadge channel={po.created_via} compact /></span>
                </TableCell>
                {!isSupplier && <TableCell>{po.supplier_name}</TableCell>}
                <TableCell>
                  <StatusBadge status={po.status} />
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  <StatusBadge status={po.delivery_status} />
                </TableCell>
                <TableCell className="text-right">{money(po.total_amount)}</TableCell>
                <TableCell className="hidden md:table-cell">{shortDate(po.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
