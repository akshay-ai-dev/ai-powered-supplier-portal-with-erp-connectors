"use client";
import { useEffect, useState } from "react";
import { Truck } from "lucide-react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { api, uploadFile } from "@/lib/api";
import { AiBanner, useAiFill } from "@/lib/prefill";
import { cn } from "@/lib/utils";
import type { PurchaseOrder, Shipment, ToShip } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/page-header";

/**
 * Supplier ships (part of) an approved order. The quantities left come from the server, which counts only the units the
 * warehouse accepted, so faulty or missing units can be shipped again. When an earlier shipment still has units to
 * replace, the form offers to link the new shipment to it and lists those units.
 */
export function ShipForm({ po, toShip, onDone, initialReplace }: { po: PurchaseOrder; toShip: ToShip; onDone: () => void; initialReplace?: string | null }) {
  const left = new Map(toShip.progress.map((p) => [p.item_code.toUpperCase(), p.left]));
  const remaining = po.items.map((i) => ({ item_code: i.item_code, left: left.get(i.item_code.toUpperCase()) ?? 0 }));
  const asked = toShip.replace.find((r) => String(r.shipment_id) === initialReplace); // opened from a shipment's "resend" button
  const [replaces, setReplaces] = useState<string>(asked ? String(asked.shipment_id) : toShip.replace[0] ? String(toShip.replace[0].shipment_id) : "");
  useEffect(() => {
    if (initialReplace) document.getElementById("ship-form")?.scrollIntoView({ block: "start" });
  }, [initialReplace]);
  const owedTotal = (code: string) => toShip.replace.reduce((n, r) => n + (r.items.find((d) => d.item_code.toUpperCase() === code.toUpperCase())?.outstanding ?? 0), 0);
  // replacing: only the owed items, at most what is owed. Otherwise every item with something left, starting
  // from the part that is new goods (what is owed is shipped as a replacement, so it is not suggested twice).
  const rowsFor = (t: ToShip["replace"][number] | undefined) =>
    t
      ? t.items.map((d) => {
          const own = remaining.find((r) => r.item_code.toUpperCase() === d.item_code.toUpperCase())?.item_code ?? d.item_code;
          const max = Math.min(d.outstanding, left.get(d.item_code.toUpperCase()) ?? d.outstanding);
          return { item_code: own, left: max, start: max };
        })
      : remaining.map((r) => ({ ...r, start: Math.max(r.left - owedTotal(r.item_code), 0) }));
  const target = toShip.replace.find((r) => String(r.shipment_id) === replaces);
  const lines = rowsFor(target);
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(lines.map((r) => [r.item_code, String(r.start)])));
  function pickTarget(value: string) {
    setReplaces(value);
    setQty(Object.fromEntries(rowsFor(toShip.replace.find((r) => String(r.shipment_id) === value)).map((r) => [r.item_code, String(r.start)])));
  }
  const [f, setF] = useState({ carrier: "", tracking_no: "", expected_arrival: "", notes: "" });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [qr, setQr] = useState(true);
  const router = useRouter();
  const ai = useAiFill(
    "ship_order",
    (v) => {
      const byCode = new Map(remaining.map((r) => [r.item_code.toUpperCase(), r.item_code]));
      setQty((q) => {
        const next = { ...q };
        for (const [code, n] of Object.entries(v.quantities ?? {})) {
          const key = byCode.get(code.toUpperCase());
          if (key) next[key] = String(n);
        }
        return next;
      });
      setF((p) => ({
        carrier: v.carrier ?? p.carrier,
        tracking_no: v.tracking_no ?? p.tracking_no,
        expected_arrival: v.expected_arrival ?? p.expected_arrival,
        notes: v.notes ?? p.notes,
      }));
    },
    po.id,
  );

  if (remaining.every((r) => r.left === 0)) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const items = lines.map((r) => ({ item_code: r.item_code, quantity: Number(qty[r.item_code] || 0) })).filter((i) => i.quantity > 0);
    if (items.length === 0) return setError("Enter a quantity for at least one item.");
    setBusy(true);
    try {
      const sh = await api<Shipment>(`/api/purchase-orders/${po.id}/shipments`, {
        body: { carrier: f.carrier, tracking_no: f.tracking_no, expected_arrival: f.expected_arrival || null, notes: f.notes, items, unit_inspection: qr, replaces_shipment_id: target?.shipment_id ?? null },
      });
      if (file) {
        try {
          await uploadFile(`/api/shipments/${sh.id}/files?kind=packing_list`, file);
        } catch (err) {
          toast.error(`Shipment created, but the packing list was not attached: ${err instanceof Error ? err.message : "failed"}. Add it from the shipment page.`);
        }
      }
      toast.success(`${sh.shipment_no} submitted. The warehouse has been notified.`);
      if (qr) {
        toast.info("Print the QR labels and stick one on each item.");
        router.push(`/shipments/${sh.id}/labels`);
        return;
      }
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create shipment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-6" id="ship-form">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Truck className="size-4" />
          Ship this order
        </CardTitle>
        <CardDescription>Attach your packing list. The warehouse inspects the goods on arrival and releases the stock.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <AiBanner show={ai.any} onDismiss={ai.clear} />
          {toShip.replace.length > 0 && (
            <div className="space-y-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
              <div>
                <b>Units from an earlier shipment still need replacing.</b> Link this shipment to the one it replaces, so the warehouse and the buyer can see which units it makes good.
              </div>
              <div className="space-y-1">
                <Label htmlFor="replaces">This shipment replaces</Label>
                <select
                  id="replaces"
                  value={replaces}
                  onChange={(e) => pickTarget(e.target.value)}
                  className="flex h-9 w-full max-w-md rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs"
                >
                  {toShip.replace.map((r) => (
                    <option key={r.shipment_id} value={r.shipment_id}>
                      {r.shipment_no} ({r.status === "Rejected" ? "rejected" : "approved with faulty or missing units"}): {r.items.map((d) => `${d.outstanding} × ${d.item_code}`).join(", ")}
                    </option>
                  ))}
                  <option value="">Nothing: these are new goods, not a replacement</option>
                </select>
              </div>
              {target && target.status === "Rejected" && <p className="text-muted-foreground">The whole lot was rejected, so every unit of it is to be shipped again with new QR codes.</p>}
              {target && target.units.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Units to replace from {target.shipment_no}</div>
                  <div className="max-h-48 overflow-y-auto rounded-md border bg-background">
                    <table className="w-full text-left text-xs">
                      <thead className="sticky top-0 bg-background text-muted-foreground">
                        <tr><th className="p-2">Unit</th><th>Problem</th><th>Inspector&apos;s note</th></tr>
                      </thead>
                      <tbody>
                        {target.units.map((u) => (
                          <tr key={u.code} className="border-t align-top">
                            <td className="p-2 font-mono">{u.code}</td>
                            <td>{u.status === "Missing" ? "Never arrived" : u.defect_label || "Faulty"}</td>
                            <td className="pr-2 text-muted-foreground">{u.notes || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">The replacements get new QR codes. Print the new labels; the old codes stay with the units that failed.</p>
                </div>
              )}
            </div>
          )}
          <div className="space-y-2">
            <Label>Quantities in this shipment</Label>
            {lines.map((r) => (
              <div key={r.item_code} className="flex items-center gap-3 text-sm">
                <span className="w-32 font-mono text-xs">{r.item_code}</span>
                <Input aria-label={`Quantity of ${r.item_code}`} className={cn("w-28", ai.ring("quantities"))} type="number" min={0} max={r.left} value={qty[r.item_code] ?? ""} onChange={(e) => setQty({ ...qty, [r.item_code]: e.target.value })} />
                <span className="text-xs text-muted-foreground">{target ? `${r.left} to replace` : `${r.left} still to ship`}</span>
              </div>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="carrier">Carrier</Label>
              <Input id="carrier" value={f.carrier} onChange={(e) => setF({ ...f, carrier: e.target.value })} className={ai.ring("carrier")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="track">Tracking number</Label>
              <Input id="track" value={f.tracking_no} onChange={(e) => setF({ ...f, tracking_no: e.target.value })} className={ai.ring("tracking_no")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="eta">Expected arrival</Label>
              <Input id="eta" type="date" value={f.expected_arrival} onChange={(e) => setF({ ...f, expected_arrival: e.target.value })} className={ai.ring("expected_arrival")} />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="pl">Packing list (PDF, Excel, CSV, image; max 10 MB)</Label>
            <Input id="pl" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="sn">Notes for the warehouse</Label>
            <Input id="sn" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={ai.ring("notes")} />
          </div>
          <label className="flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm">
            <input type="checkbox" className="mt-1" checked={qr} onChange={(e) => setQr(e.target.checked)} />
            <span>
              <b>Give every unit its own QR code</b>
              <span className="block text-xs text-muted-foreground">You print one label per unit and stick it on the item. The warehouse scans each code on arrival and tests the units one by one, so you get a report on every unit. Untick for bulk goods that are inspected as one lot.</span>
            </span>
          </label>
          <ErrorNote message={error} />
          <Button type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Submit shipment"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
