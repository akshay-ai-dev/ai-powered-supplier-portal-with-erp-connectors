"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { use, useEffect, useState } from "react";
import { ArrowLeft, Download, FileText, ImageIcon } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime, downloadFile, fileSize, shortDate, uploadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { Shipment, ShipmentFile } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { LotReportCard, UnitDecisionCard } from "@/components/lot-report";
import { ReceivePanel } from "@/components/receive-panel";
import { UnitInspection } from "@/components/unit-inspection";
import { StatusBadge } from "@/components/status-badge";

function FileRow({ f }: { f: ShipmentFile }) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="flex min-w-0 items-center gap-2">
        {f.kind === "photo" ? <ImageIcon className="size-4 shrink-0" /> : <FileText className="size-4 shrink-0" />}
        <span className="truncate">{f.filename}</span>
        <span className="text-xs text-muted-foreground">({fileSize(f.size)})</span>
      </span>
      <Button variant="ghost" size="icon" aria-label={`Download ${f.filename}`} onClick={() => downloadFile(`/api/shipment-files/${f.id}/download`, f.filename).catch((e) => toast.error(e.message))}>
        <Download className="size-4" />
      </Button>
    </div>
  );
}

export default function ShipmentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user } = useAuth();
  const { data: s, error, loading, reload } = useFetch<Shipment>(`/api/shipments/${id}`);
  const [busy, setBusy] = useState(false);
  const [received, setReceived] = useState<Record<string, string>>({});
  const [arrivalNotes, setArrivalNotes] = useState("");
  const [decisionNotes, setDecisionNotes] = useState("");
  const [reason, setReason] = useState("");
  const [checks, setChecks] = useState<Record<string, boolean | null>>({});
  const [improvement, setImprovement] = useState("");
  const [version, setVersion] = useState(0);
  const query = useSearchParams();

  useEffect(() => {
    if (s) setReceived(Object.fromEntries(s.items.map((i) => [i.item_code, String(i.quantity_received ?? i.quantity_shipped)])));
  }, [s]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error || !s) return <ErrorNote message={error ?? "Not found"} />;

  const inspector = user?.role === "inspector" || user?.role === "admin";
  const isSupplier = user?.role === "supplier";
  const decided = s.status === "Approved" || s.status === "Rejected";
  const unitLevel = !!s.unit_level;
  const owes = !!s.owed && s.owed.length > 0;
  const superseded = !!s.replaced_by?.some((r) => r.status === "Rejected"); // a rejected replacement now carries what this one owed
  const changed = () => {
    setVersion((n) => n + 1);
    void reload();
  };
  const allPass = s.quality.every((q) => checks[q.key] === true);
  const explicitChecks = Object.fromEntries(Object.entries(checks).filter(([, v]) => v !== null && v !== undefined));

  return (
    <>
      <Link href="/shipments" className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="mr-1 size-4" />
        All shipments
      </Link>
      <PageHeader title={s.shipment_no} description={`${s.supplier_name} · order ${s.po_number} · submitted ${dateTime(s.created_at)}`}>
        <StatusBadge status={s.status} />
        {unitLevel && isSupplier && (
          <Link href={`/shipments/${s.id}/labels`}>
            <Button variant="outline">Print QR labels</Button>
          </Link>
        )}
      </PageHeader>

      {isSupplier && owes && !superseded && (
        <div role="status" className={`mb-6 flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm ${s.status === "Rejected" ? "border-destructive/40 bg-destructive/10 text-destructive" : "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-200"}`}>
          <span>
            <b>{s.status === "Rejected" ? "This shipment was rejected." : "Some units need replacing."}</b> Still to replace: {s.owed?.map((d) => `${d.quantity} × ${d.item_code}`).join(", ")}.
          </span>
          <Link href={`/purchase-orders/${s.po_id}?replace=${s.id}`}>
            <Button>{s.status === "Rejected" ? "Resend this shipment" : "Ship a replacement"}</Button>
          </Link>
        </div>
      )}
      {(s.replaces_shipment_id || (s.replaced_by && s.replaced_by.length > 0) || (!isSupplier && owes)) && (
        <div role="status" className="mb-6 space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200">
          {s.replaces_shipment_id && (
            <p>
              <b>Replacement shipment.</b> It replaces the faulty, missing or rejected units of{" "}
              <Link className="font-medium underline" href={`/shipments/${s.replaces_shipment_id}`}>{s.replaces_shipment_no}</Link>.
            </p>
          )}
          {s.replaced_by?.map((r) => (
            <p key={r.id}>
              <b>Replaced by</b>{" "}
              <Link className="font-medium underline" href={`/shipments/${r.id}`}>{r.shipment_no}</Link> ({r.status.toLowerCase()}).
            </p>
          ))}
          {!isSupplier && owes && <p>Still to replace: {s.owed?.map((d) => `${d.quantity} × ${d.item_code}`).join(", ")}.</p>}
        </div>
      )}
      {s.status === "Rejected" && (
        <p role="status" className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <b>Rejected at inspection:</b> {s.rejection_reason}. The goods are in quarantine and the invoice is on hold. A replacement shipment is needed.
        </p>
      )}
      {s.status === "Approved" && (
        <p role="status" className="mb-6 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300">
          <b>Approved.</b> Stock has been released{s.inspected_at ? ` on ${dateTime(s.inspected_at)}` : ""}.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-sm">
            <div><div className="text-muted-foreground">Carrier</div>{s.carrier || "—"}</div>
            <div><div className="text-muted-foreground">Tracking</div>{s.tracking_no || "—"}</div>
            <div><div className="text-muted-foreground">Expected arrival</div>{s.expected_arrival ? shortDate(s.expected_arrival) : "—"}</div>
            <div><div className="text-muted-foreground">Arrived</div>{s.arrived_at ? dateTime(s.arrived_at) : "—"}</div>
            <div><div className="text-muted-foreground">ERP</div><span className="uppercase">{s.erp}</span></div>
            <div><div className="text-muted-foreground">Inbound delivery</div>{s.erp_inbound_ref ?? "—"}</div>
            {s.erp_movement_ref && <div className="col-span-2"><div className="text-muted-foreground">ERP stock document</div>{s.erp_movement_ref}</div>}
            {s.notes && <p className="col-span-2 whitespace-pre-wrap"><span className="text-muted-foreground">Supplier notes: </span>{s.notes}</p>}
            {s.inspection_notes && <p className="col-span-2 whitespace-pre-wrap"><span className="text-muted-foreground">Inspector notes: </span>{s.inspection_notes}</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Files</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-xs font-medium uppercase text-muted-foreground">Packing list</div>
            {s.packing_list ? <FileRow f={s.packing_list} /> : <p className="text-sm text-muted-foreground">None attached.</p>}
            {isSupplier && s.status === "Shipped" && (
              <div>
                <Label htmlFor="pl" className="mb-1 block text-xs text-muted-foreground">{s.packing_list ? "Replace" : "Attach"} packing list</Label>
                <Input
                  id="pl"
                  type="file"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) run(() => uploadFile(`/api/shipments/${id}/files?kind=packing_list`, f), "Packing list attached");
                  }}
                />
              </div>
            )}
            <div className="pt-2 text-xs font-medium uppercase text-muted-foreground">Inspection photos</div>
            {s.photos.length === 0 && <p className="text-sm text-muted-foreground">None.</p>}
            {s.photos.map((f) => (
              <FileRow key={f.id} f={f} />
            ))}
            {inspector && s.status === "Arrived" && (
              <div>
                <Label htmlFor="photo" className="mb-1 block text-xs text-muted-foreground">Add a photo (png, jpg, gif, webp)</Label>
                <Input
                  id="photo"
                  type="file"
                  accept="image/*"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    e.target.value = "";
                    if (f) run(() => uploadFile(`/api/shipments/${id}/files?kind=photo`, f), "Photo added");
                  }}
                />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Items</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead className="text-right">Shipped</TableHead>
                <TableHead className="text-right">Received</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {s.items.map((i) => (
                <TableRow key={i.item_code}>
                  <TableCell className="font-mono text-xs">{i.item_code}</TableCell>
                  <TableCell className="text-right">{i.quantity_shipped}</TableCell>
                  <TableCell className="text-right">
                    {inspector && s.status === "Shipped" && !unitLevel ? (
                      <Input
                        aria-label={`Received quantity of ${i.item_code}`}
                        className="ml-auto w-24 text-right"
                        type="number"
                        min={0}
                        max={i.quantity_shipped}
                        value={received[i.item_code] ?? ""}
                        onChange={(e) => setReceived({ ...received, [i.item_code]: e.target.value })}
                      />
                    ) : (
                      i.quantity_received == null ? (
                        "—"
                      ) : i.quantity_received < i.quantity_shipped ? (
                        <span className="text-amber-700 dark:text-amber-400">
                          {i.quantity_received} <span className="text-xs">(short by {i.quantity_shipped - i.quantity_received})</span>
                        </span>
                      ) : (
                        i.quantity_received
                      )
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {decided && !unitLevel && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Inspection result</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="space-y-1">
              {s.quality.map((q) => (
                <li key={q.key} className="flex items-center gap-2">
                  <span className={q.passed === true ? "text-emerald-600" : q.passed === false ? "text-destructive" : "text-muted-foreground"}>
                    {q.passed === true ? "✓ Passed" : q.passed === false ? "✗ Failed" : "– Not recorded"}
                  </span>
                  <span>{q.label}</span>
                </li>
              ))}
            </ul>
            {s.status === "Rejected" && s.improvement_request && (
              <div className="rounded-md border p-3">
                <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">What the supplier must improve</div>
                <p className="whitespace-pre-wrap">{s.improvement_request}</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {inspector && s.status === "Shipped" && unitLevel && <ReceivePanel s={s} version={version} onChanged={changed} />}

      {unitLevel && (s.status !== "Shipped" || isSupplier || !inspector) && <UnitInspection s={s} inspector={inspector} version={version} onChanged={changed} openCode={query?.get("unit")} />}
      {unitLevel && s.status !== "Shipped" && <LotReportCard shipmentId={s.id} version={version} />}

      {inspector && s.status === "Shipped" && !unitLevel && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Record arrival</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">Count what physically arrived and enter it above, then confirm.</p>
            <Textarea aria-label="Arrival notes" placeholder="Condition on arrival, damage to packaging, etc. (optional)" value={arrivalNotes} onChange={(e) => setArrivalNotes(e.target.value)} />
            <Button
              disabled={busy}
              onClick={() =>
                run(
                  () => api(`/api/shipments/${id}/arrival`, { body: { lines: s.items.map((i) => ({ item_code: i.item_code, quantity_received: Number(received[i.item_code] ?? 0) })), notes: arrivalNotes } }),
                  "Arrival recorded",
                )
              }
            >
              Confirm arrival
            </Button>
          </CardContent>
        </Card>
      )}

      {inspector && s.status === "Arrived" && unitLevel && <UnitDecisionCard s={s} version={version} onDone={changed} />}

      {inspector && s.status === "Arrived" && !unitLevel && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Inspection decision</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="text-sm font-medium">Quality checks</div>
              {s.quality.map((q) => (
                <div key={q.key} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
                  <span>{q.label}</span>
                  <span className="flex gap-1" role="radiogroup" aria-label={q.label}>
                    {([true, false] as const).map((v) => (
                      <button
                        key={String(v)}
                        type="button"
                        role="radio"
                        aria-checked={checks[q.key] === v}
                        onClick={() => setChecks({ ...checks, [q.key]: v })}
                        className={`rounded-md border px-3 py-1 text-xs ${
                          checks[q.key] === v ? (v ? "border-emerald-600 bg-emerald-500/15 font-medium" : "border-destructive bg-destructive/15 font-medium") : "text-muted-foreground hover:bg-accent/50"
                        }`}
                      >
                        {v ? "Pass" : "Fail"}
                      </button>
                    ))}
                  </span>
                </div>
              ))}
              <p className="text-xs text-muted-foreground">Approving needs all four checks to pass. Received quantities are compared with what was shipped in the table above.</p>
            </div>
            <Textarea aria-label="Inspection notes" placeholder="Inspection notes (optional)" value={decisionNotes} onChange={(e) => setDecisionNotes(e.target.value)} />
            <div className="flex flex-wrap items-start gap-6">
              <div>
                <Button disabled={busy || !allPass} onClick={() => run(() => api(`/api/shipments/${id}/inspection`, { body: { decision: "approve", notes: decisionNotes, checks: explicitChecks } }), "Approved. Stock released.")}>
                  Approve and release stock
                </Button>
                {!allPass && <p className="mt-2 max-w-52 text-xs text-muted-foreground">Mark every quality check as Pass to approve.</p>}
              </div>
              <div className="min-w-64 flex-1 space-y-2">
                <Input aria-label="Rejection reason" placeholder="Rejection reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
                <Textarea aria-label="What the supplier must improve" placeholder="What must the supplier fix or improve? (sent to them)" value={improvement} onChange={(e) => setImprovement(e.target.value)} maxLength={1000} />
                <Button
                  variant="destructive"
                  disabled={busy || reason.trim().length < 3 || s.photos.length === 0}
                  onClick={() => run(() => api(`/api/shipments/${id}/inspection`, { body: { decision: "reject", reason, notes: decisionNotes, checks: explicitChecks, improvement } }), "Rejected. The supplier has been asked to improve and replace.")}
                >
                  Reject: quarantine and hold invoice
                </Button>
                {s.photos.length === 0 && <p className="text-xs text-muted-foreground">Add at least one photo above before rejecting.</p>}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {!inspector && !decided && (
        <p className="mt-6 text-sm text-muted-foreground">
          {s.status === "Shipped" ? "The shipment is on its way. The warehouse will record its arrival." : "The shipment has arrived and is awaiting the inspector's decision."}
        </p>
      )}
    </>
  );
}
