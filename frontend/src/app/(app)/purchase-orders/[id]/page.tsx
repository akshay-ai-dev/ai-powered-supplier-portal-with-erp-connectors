"use client";
import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime, money } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { POStatus, PurchaseOrder, Shipment } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { AgentBadge } from "@/components/agent-badge";
import { HistoryCard } from "@/components/history-card";
import { MessageThread } from "@/components/message-thread";
import { ShipForm } from "@/components/ship-form";

const NEXT_STATUS: Partial<Record<POStatus, { to: POStatus; label: string }>> = {
  Draft: { to: "Pending", label: "Submit for approval" },
  Pending: { to: "Approved", label: "Approve" },
  Approved: { to: "Closed", label: "Close order" },
};

export default function PurchaseOrderDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user } = useAuth();
  const { data: po, error, loading, reload } = useFetch<PurchaseOrder>(`/api/purchase-orders/${id}`);
  const [busy, setBusy] = useState(false);
  const shipments = useFetch<Shipment[]>(`/api/purchase-orders/${id}/shipments`);

  async function change(body: { status?: POStatus }, okMsg: string) {
    setBusy(true);
    try {
      await api(`/api/purchase-orders/${id}`, { method: "PUT", body });
      toast.success(okMsg);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error || !po) return <ErrorNote message={error ?? "Not found"} />;

  const isSupplier = user?.role === "supplier";
  const canWrite = user?.role === "buyer" || user?.role === "admin";
  const step = NEXT_STATUS[po.status];
  const closeBlocked = step?.to === "Closed" && po.delivery_status !== "Delivered";
  const canShip = isSupplier && po.status === "Approved" && po.delivery_status !== "Delivered";

  return (
    <>
      <Link href="/purchase-orders" className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="mr-1 size-4" />
        All orders
      </Link>
      <PageHeader title={po.po_number} description={`${po.supplier_name} · created ${dateTime(po.created_at)}`}>
        <AgentBadge channel={po.created_via} />
        <StatusBadge status={po.status} />
        <StatusBadge status={po.delivery_status} />
      </PageHeader>

      <div className="mb-6 flex flex-wrap gap-2">
        {canWrite && step && (
          <Button disabled={busy || closeBlocked} onClick={() => change({ status: step.to }, `Order ${step.to.toLowerCase()}`)}>
            {step.label}
          </Button>
        )}
        {canWrite && closeBlocked && <span className="self-center text-xs text-muted-foreground">Can be closed after delivery.</span>}
        {isSupplier && po.status !== "Approved" && po.delivery_status !== "Delivered" && (
          <span className="text-sm text-muted-foreground">You can ship this order once the buyer has approved it.</span>
        )}
      </div>

      {po.invoice_hold ? (
        <p role="status" className="mb-6 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
          <b>Invoice on hold.</b> {po.invoice_hold_reason ? `Reason: ${po.invoice_hold_reason}. ` : ""}Payment stays blocked until a replacement shipment passes inspection.
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Items</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Unit price</TableHead>
                <TableHead className="text-right">Line total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {po.items.map((i, idx) => (
                <TableRow key={idx}>
                  <TableCell className="font-mono text-xs">{i.item_code}</TableCell>
                  <TableCell className="text-right">{i.quantity}</TableCell>
                  <TableCell className="text-right">{money(i.unit_price)}</TableCell>
                  <TableCell className="text-right">{money(i.quantity * i.unit_price)}</TableCell>
                </TableRow>
              ))}
              <TableRow>
                <TableCell colSpan={3} className="text-right font-medium">
                  Total
                </TableCell>
                <TableCell className="text-right font-semibold">{money(po.total_amount)}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
          {po.erp_reference && <p className="mt-4 text-xs text-muted-foreground">ERP reference: {po.erp_reference}</p>}
        </CardContent>
      </Card>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Shipments</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {shipments.data?.length === 0 && <p className="text-sm text-muted-foreground">No shipments yet.</p>}
          {shipments.data?.map((s) => (
            <div key={s.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="flex flex-wrap items-center gap-2">
                <Link className="font-medium underline-offset-4 hover:underline" href={`/shipments/${s.id}`}>
                  {s.shipment_no}
                </Link>
                <StatusBadge status={s.status} />
                <span className="text-muted-foreground">{s.items.map((i) => `${i.quantity_shipped} × ${i.item_code}`).join(", ")}</span>
                {s.tracking_no && <span className="text-xs text-muted-foreground">tracking {s.tracking_no}</span>}
              </span>
              <span className="text-xs text-muted-foreground">{dateTime(s.created_at)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
      {canShip && shipments.data && <ShipForm po={po} shipments={shipments.data} onDone={() => { reload(); shipments.reload(); }} />}
      {po.requirement_id && (canWrite || isSupplier) && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>
              Messages with {isSupplier ? "the buyer" : po.supplier_name}{" "}
              <Link className="text-xs font-normal text-muted-foreground underline" href={`/requirements/${po.requirement_id}`}>
                (requirement)
              </Link>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MessageThread requirementId={po.requirement_id} supplierId={isSupplier ? undefined : po.supplier_id} />
          </CardContent>
        </Card>
      )}
      <HistoryCard history={po.history} />
    </>
  );
}
