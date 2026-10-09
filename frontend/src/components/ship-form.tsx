"use client";
import { useEffect, useState } from "react";
import { FileSearch, Truck } from "lucide-react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import { api, uploadFile } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ExtractionDraft, FieldIssue, PurchaseOrder, QuantityComparison, Shipment, ToShip } from "@/lib/types";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/page-header";

// Plain-language reasons for the "Needs review" section; falls back to the model's own message.
const ISSUE_TEXT: Record<string, string> = {
  not_found: "not found in the document — enter it if you have it.",
  customer_collection: "the document says customer collection, so no carrier is shown.",
  carrier_not_in_reference_list: "kept as written (not a standard parcel carrier).",
  ambiguous_date: "the date is numerically ambiguous — confirm the day and month.",
  inferred_from_document_date: "taken from the document date, not an explicit ship-date label — confirm it.",
  ambiguous_value: "a value looked like this field but was unclear, so it was left out.",
  multiple_items: "the document lists several different items, so there is no single shipped total — enter the quantity per line.",
  mixed_units: "the lines use different units, so there is no single shipped total.",
  unit_not_stated: "no unit of measure is printed.",
  weight_not_item_quantity: "only a gross weight is shown, which is not an item count — enter the shipped item quantity.",
  packaging_not_item_quantity: "only a package/carton count is shown, not an item quantity — enter the shipped item quantity.",
  only_packaging_or_weight: "only package counts and/or a gross weight are shown, not an item quantity — enter the shipped item quantity.",
  repeated_line_merged: "a repeated line was counted once.",
};
const FIELD_LABEL: Record<string, string> = {
  ship_date: "Ship date",
  carrier: "Carrier",
  tracking_numbers: "Tracking numbers",
  shipped_quantity: "Shipped quantity",
  unit_of_measure: "Unit",
  lot_numbers: "Lot numbers",
  serial_numbers: "Serial numbers",
  items: "Line items",
};

/**
 * Supplier ships (part of) an approved order. The quantities left come from the server, which counts only the units the
 * warehouse accepted, so faulty or missing units can be shipped again. The form can pre-fill from a packing-list
 * document (PDF or image): upload (A) → review the six extracted fields with evidence (B) → needs-review reasons (C).
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
  const startFor = new Map(lines.map((r) => [r.item_code, String(r.start)]));
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(lines.map((r) => [r.item_code, String(r.start)])));
  function pickTarget(value: string) {
    setReplaces(value);
    setQty(Object.fromEntries(rowsFor(toShip.replace.find((r) => String(r.shipment_id) === value)).map((r) => [r.item_code, String(r.start)])));
  }
  const [f, setF] = useState({ carrier: "", expected_arrival: "", notes: "" });
  const [tracking, setTracking] = useState(""); // one tracking number per line
  const [file, setFile] = useState<File | null>(null);
  const [docUrl, setDocUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [qr, setQr] = useState(true);
  // Extracted packing-list draft under review. Carrier and tracking flow into the shipment; ship date,
  // shipped quantity/unit, lots and serials are reviewed here and preserved via the attached document
  // plus a summary in notes (the shipment record has no columns for them).
  const [pl, setPl] = useState({ ship_date: "", shipped_quantity: "", unit_of_measure: "", lots: "", serials: "" });
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [evidence, setEvidence] = useState<ExtractionDraft["evidence"]>([]);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [cmp, setCmp] = useState<QuantityComparison | null>(null);
  const router = useRouter();
  const linesToArray = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  const distinctCodes = [...new Set(po.items.map((i) => i.item_code.toUpperCase()))];
  const shippable = lines.map((r) => r.item_code);
  const [applyItem, setApplyItem] = useState<string>(shippable.length === 1 ? shippable[0] : "");

  // Keep an object URL so the supplier can open the uploaded document while reviewing.
  useEffect(() => {
    if (!file) {
      setDocUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setDocUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const evidenceFor = (field: string) => evidence.filter((e) => e.field === field);

  async function runCompare(shippedQty: string, itemCode: string | null) {
    const n = shippedQty.trim() === "" ? null : Number(shippedQty);
    if (!itemCode && distinctCodes.length > 1) {
      setCmp(null); // need the supplier to choose which item first
      return;
    }
    try {
      const res = await api<QuantityComparison>(`/api/extraction-prefill/shipments/${po.id}/compare`, {
        body: { shipped_quantity: Number.isFinite(n as number) ? n : null, item_code: itemCode },
      });
      setCmp(res);
    } catch {
      setCmp(null);
    }
  }

  // Upload one packing-list PDF/image for extraction. Saves nothing; only fills the review fields and
  // becomes the attached document on submit. Never writes the shipped quantity into item quantities.
  async function extractDoc(doc: File) {
    setError(null);
    setExtracting(true);
    try {
      const d = await uploadFile<ExtractionDraft>(`/api/extraction-prefill/shipments/${po.id}`, doc);
      setF((p) => ({ ...p, carrier: d.carrier ?? p.carrier }));
      setTracking((d.tracking_numbers ?? []).join("\n"));
      setPl({
        ship_date: d.ship_date ?? "",
        shipped_quantity: d.shipped_quantity != null ? String(d.shipped_quantity) : "",
        unit_of_measure: d.unit_of_measure ?? "",
        lots: (d.lot_numbers ?? []).join("\n"),
        serials: (d.serial_numbers ?? []).join("\n"),
      });
      setIssues(d.field_issues ?? []);
      setEvidence(d.evidence ?? []);
      setFile(doc);
      const q = d.shipped_quantity != null ? String(d.shipped_quantity) : "";
      await runCompare(q, applyItem || (shippable.length === 1 ? shippable[0] : null));
      toast.success("Draft extracted. Review every field before submitting — nothing has been saved yet.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not read the document.");
    } finally {
      setExtracting(false);
    }
  }

  function applyQuantityToLine() {
    if (!applyItem || !pl.shipped_quantity) return;
    const current = qty[applyItem] ?? "";
    const start = startFor.get(applyItem) ?? "";
    // do not silently overwrite a value the supplier has already changed from the default
    if (current && current !== start && current !== pl.shipped_quantity) {
      if (!window.confirm(`Replace the current quantity (${current}) for ${applyItem} with ${pl.shipped_quantity}?`)) return;
    }
    setQty((p) => ({ ...p, [applyItem]: pl.shipped_quantity }));
  }



  if (remaining.every((r) => r.left === 0)) return null;

  // Unique needs-review reasons (no raw JSON, no duplicates).
  const seen = new Set<string>();
  const reviewReasons = issues.filter((it) => {
    const k = `${it.field}:${it.code}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const items = lines.map((r) => ({ item_code: r.item_code, quantity: Number(qty[r.item_code] || 0) })).filter((i) => i.quantity > 0);
    if (items.length === 0) return setError("Enter a quantity for at least one item.");
    setBusy(true);
    try {
      const trackingList = linesToArray(tracking);
      const lots = linesToArray(pl.lots);
      const serials = linesToArray(pl.serials);
      // The shipment column tracking_no holds one value (max 80) for the existing views/notifications;
      // the full reviewed draft (all tracking/lot/serial numbers, ship date, shipped qty/unit) is saved
      // in packing_list_review, which has no length limit — so nothing is dropped or lost to notes.
      const joined = trackingList.join(", ");
      const tracking_no = joined.length <= 80 ? joined : trackingList[0] ?? "";
      const hasReview = !!(pl.ship_date || pl.shipped_quantity || trackingList.length || lots.length || serials.length || f.carrier);
      const packing_list_review = hasReview
        ? {
            ship_date: pl.ship_date || null,
            carrier: f.carrier || null,
            shipped_quantity: pl.shipped_quantity ? Number(pl.shipped_quantity) : null,
            unit_of_measure: pl.unit_of_measure || null,
            tracking_numbers: trackingList,
            lot_numbers: lots,
            serial_numbers: serials,
          }
        : null;
      const sh = await api<Shipment>(`/api/purchase-orders/${po.id}/shipments`, {
        body: { carrier: f.carrier, tracking_no, expected_arrival: f.expected_arrival || null, notes: f.notes, packing_list_review, items, unit_inspection: qr, replaces_shipment_id: target?.shipment_id ?? null },
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

  // Label + control + an Evidence toggle that shows the model-supplied page/text, or a clear fallback.
  const field = (key: string, label: string, control: React.ReactNode, extra?: React.ReactNode) => {
    const ev = evidenceFor(key);
    const open = openEvidence === key;
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <Label>{label}</Label>
          <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground underline" onClick={() => setOpenEvidence(open ? null : key)}>
            <FileSearch className="size-3" /> Evidence
          </button>
        </div>
        {control}
        {extra}
        {open && (
          <div className="rounded-md border bg-muted/40 p-2 text-xs">
            {ev.length > 0 ? (
              <ul className="space-y-1">
                {ev.map((e, i) => (
                  <li key={i}>
                    {e.page != null ? <b>Page {e.page}: </b> : <b>Source text: </b>}
                    <span className="italic">“{e.text}”</span>
                  </li>
                ))}
                <li className="text-muted-foreground">As reported by the extractor; please confirm against the document.</li>
              </ul>
            ) : (
              <span className="text-muted-foreground">Source location unavailable.</span>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <Card className="mt-6" id="ship-form">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Truck className="size-4" />
          Ship this order
        </CardTitle>
        <CardDescription>Optionally pre-fill from your packing list, review every field, then submit. The warehouse inspects the goods on arrival and releases the stock.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">

          {/* A. Upload */}
          <fieldset className="space-y-2 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">A. Upload packing list or delivery note</legend>
            <Label htmlFor="extract">PDF or image (max 10 MB)</Label>
            <Input
              id="extract"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,application/pdf,image/*"
              disabled={extracting}
              onChange={(e) => {
                const doc = e.target.files?.[0];
                e.target.value = "";
                if (doc) extractDoc(doc);
              }}
            />
            <p className="text-xs text-muted-foreground" role="status">
              {extracting ? "Reading the document…" : file ? `Read “${file.name}”. It will be attached when you submit. Nothing is saved yet.` : "Optional. Values become an editable draft — never submitted automatically."}
            </p>
            {file && docUrl && (
              <a href={docUrl} target="_blank" rel="noreferrer" className="inline-block text-xs underline">
                View uploaded document
              </a>
            )}
          </fieldset>

          {/* B. Review the six fields */}
          <fieldset className="space-y-3 rounded-md border p-3">
            <legend className="px-1 text-sm font-medium">B. Review the extracted fields</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              {field("ship_date", "Ship date", <Input type="date" value={pl.ship_date} onChange={(e) => setPl({ ...pl, ship_date: e.target.value })} />)}
              {field("carrier", "Carrier", <Input value={f.carrier} onChange={(e) => setF({ ...f, carrier: e.target.value })} placeholder="FedEx, UPS, Maersk…" />)}
            </div>
            {field("tracking_numbers", "Tracking numbers", <Textarea rows={2} value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="One per line" />)}
            {field(
              "shipped_quantity",
              "Shipped quantity",
              <div className="flex gap-2">
                <Input className="w-32" type="number" min={0} step="any" value={pl.shipped_quantity} onChange={(e) => setPl({ ...pl, shipped_quantity: e.target.value })} onBlur={(e) => runCompare(e.target.value, applyItem || (shippable.length === 1 ? shippable[0] : null))} aria-label="Shipped quantity" />
                <Input className="w-28" value={pl.unit_of_measure} onChange={(e) => setPl({ ...pl, unit_of_measure: e.target.value })} placeholder="unit (EA, PR…)" aria-label="Unit" />
              </div>,
              <p className="text-xs text-muted-foreground">From the document. Package counts and gross weight are not item quantities. Apply it to a PO line below.</p>,
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              {field("lot_numbers", "Lot numbers", <Textarea rows={2} value={pl.lots} onChange={(e) => setPl({ ...pl, lots: e.target.value })} placeholder="One per line" />)}
              {field("serial_numbers", "Serial numbers", <Textarea rows={2} value={pl.serials} onChange={(e) => setPl({ ...pl, serials: e.target.value })} placeholder="One per line" />)}
            </div>
          </fieldset>

          {/* C. Needs review */}
          {reviewReasons.length > 0 && (
            <fieldset className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
              <legend className="px-1 text-sm font-medium">C. Needs review</legend>
              <ul className="space-y-1 text-xs">
                {reviewReasons.map((it, i) => (
                  <li key={i}>
                    <span className="font-medium">{FIELD_LABEL[it.field] ?? it.field}:</span> {ISSUE_TEXT[it.code] ?? it.message}
                  </li>
                ))}
              </ul>
            </fieldset>
          )}

          {toShip.replace.length > 0 && (
            <div className="space-y-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
              <div>
                <b>Units from an earlier shipment still need replacing.</b> Link this shipment to the one it replaces, so the warehouse and the buyer can see which units it makes good.
              </div>
              <div className="space-y-1">
                <Label htmlFor="replaces">This shipment replaces</Label>
                <select id="replaces" value={replaces} onChange={(e) => pickTarget(e.target.value)} className="flex h-9 w-full max-w-md rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs">
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

          {/* Apply the reviewed shipped quantity to a PO line (choose the item first when there are several). */}
          {pl.shipped_quantity && (
            <div className="space-y-2 rounded-md border p-3">
              <Label>Apply the shipped quantity ({pl.shipped_quantity}) to a PO item</Label>
              <div className="flex flex-wrap items-center gap-2">
                {distinctCodes.length > 1 ? (
                  <select
                    aria-label="PO item for the shipped quantity"
                    value={applyItem}
                    onChange={(e) => {
                      setApplyItem(e.target.value);
                      runCompare(pl.shipped_quantity, e.target.value || null);
                    }}
                    className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="">Choose the matching item…</option>
                    {shippable.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                ) : (
                  <span className="font-mono text-xs">{applyItem || shippable[0]}</span>
                )}
                <Button type="button" variant="outline" size="sm" disabled={!applyItem} onClick={applyQuantityToLine}>
                  Fill line quantity
                </Button>
              </div>
              {distinctCodes.length > 1 && !applyItem && <p className="text-xs text-muted-foreground">Choose which PO item this quantity is for. If none matches, leave the line quantities for manual entry.</p>}
              {cmp && (
                <div
                  role="status"
                  className={cn("rounded-md border px-3 py-2 text-sm", cmp.status === "match" ? "border-green-500/50 bg-green-500/10" : cmp.status === "cannot_compare" ? "border-muted bg-muted/40" : "border-amber-500/50 bg-amber-500/10")}
                >
                  {cmp.status === "match" && <b>Matches the ordered quantity{cmp.po_quantity != null ? ` (${cmp.po_quantity})` : ""}.</b>}
                  {cmp.status === "over_shipped" && <b>Over-shipment: {cmp.shipped_quantity} vs ordered {cmp.po_quantity} (+{cmp.difference}).</b>}
                  {cmp.status === "under_shipped" && <b>Under-shipment: {cmp.shipped_quantity} vs ordered {cmp.po_quantity} ({cmp.difference}). A partial shipment is allowed.</b>}
                  {cmp.status === "cannot_compare" && <b>Cannot compare to the order.</b>}
                  {cmp.reason && <span className="block text-xs text-muted-foreground">{cmp.reason}</span>}
                  <span className="block text-xs text-muted-foreground">{cmp.unit_note}</span>
                </div>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label>Quantities in this shipment</Label>
            {lines.map((r) => (
              <div key={r.item_code} className="flex items-center gap-3 text-sm">
                <span className="w-32 font-mono text-xs">{r.item_code}</span>
                <Input aria-label={`Quantity of ${r.item_code}`} className="w-28" type="number" min={0} max={r.left} value={qty[r.item_code] ?? ""} onChange={(e) => setQty({ ...qty, [r.item_code]: e.target.value })} />
                <span className="text-xs text-muted-foreground">{target ? `${r.left} to replace` : `${r.left} still to ship`}</span>
              </div>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="eta">Expected arrival</Label>
              <Input id="eta" type="date" value={f.expected_arrival} onChange={(e) => setF({ ...f, expected_arrival: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="pl-file">Replace the attached document (optional)</Label>
              <Input id="pl-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.xlsx,.xls,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="sn">Notes for the warehouse</Label>
            <Input id="sn" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
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
