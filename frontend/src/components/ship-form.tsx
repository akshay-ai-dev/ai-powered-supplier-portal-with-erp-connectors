"use client";
import { useState } from "react";
import { Truck } from "lucide-react";
import { toast } from "sonner";
import { api, uploadFile } from "@/lib/api";
import type { PurchaseOrder, Shipment } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/page-header";

/** Supplier ships (part of) an approved order. Quantities default to what is still unshipped. */
export function ShipForm({ po, shipments, onDone }: { po: PurchaseOrder; shipments: Shipment[]; onDone: () => void }) {
  const remaining = po.items.map((i) => {
    const committed = shipments
      .filter((s) => s.status !== "Rejected")
      .flatMap((s) => s.items)
      .filter((si) => si.item_code.toUpperCase() === i.item_code.toUpperCase())
      .reduce((sum, si) => sum + si.quantity_shipped, 0);
    return { item_code: i.item_code, left: Math.max(i.quantity - committed, 0) };
  });
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(remaining.map((r) => [r.item_code, String(r.left)])));
  const [f, setF] = useState({ carrier: "", tracking_no: "", expected_arrival: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (remaining.every((r) => r.left === 0)) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const items = remaining.map((r) => ({ item_code: r.item_code, quantity: Number(qty[r.item_code] || 0) })).filter((i) => i.quantity > 0);
    if (items.length === 0) return setError("Enter a quantity for at least one item.");
    setBusy(true);
    try {
      const sh = await api<Shipment>(`/api/purchase-orders/${po.id}/shipments`, {
        body: { carrier: f.carrier, tracking_no: f.tracking_no, expected_arrival: f.expected_arrival || null, notes: f.notes, items },
      });
      if (file) {
        try {
          await uploadFile(`/api/shipments/${sh.id}/files?kind=packing_list`, file);
        } catch (err) {
          toast.error(`Shipment created, but the packing list was not attached: ${err instanceof Error ? err.message : "failed"}. Add it from the shipment page.`);
        }
      }
      toast.success(`${sh.shipment_no} submitted. The warehouse has been notified.`);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create shipment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Truck className="size-4" />
          Ship this order
        </CardTitle>
        <CardDescription>Attach your packing list. The warehouse inspects the goods on arrival and releases the stock.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label>Quantities in this shipment</Label>
            {remaining.map((r) => (
              <div key={r.item_code} className="flex items-center gap-3 text-sm">
                <span className="w-32 font-mono text-xs">{r.item_code}</span>
                <Input aria-label={`Quantity of ${r.item_code}`} className="w-28" type="number" min={0} max={r.left} value={qty[r.item_code] ?? ""} onChange={(e) => setQty({ ...qty, [r.item_code]: e.target.value })} />
                <span className="text-xs text-muted-foreground">{r.left} still to ship</span>
              </div>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="carrier">Carrier</Label>
              <Input id="carrier" value={f.carrier} onChange={(e) => setF({ ...f, carrier: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="track">Tracking number</Label>
              <Input id="track" value={f.tracking_no} onChange={(e) => setF({ ...f, tracking_no: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="eta">Expected arrival</Label>
              <Input id="eta" type="date" value={f.expected_arrival} onChange={(e) => setF({ ...f, expected_arrival: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="pl">Packing list (PDF, Excel, CSV, image; max 10 MB)</Label>
            <Input id="pl" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="sn">Notes for the warehouse</Label>
            <Input id="sn" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
          </div>
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Submit shipment"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
