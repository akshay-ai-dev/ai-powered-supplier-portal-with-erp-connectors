"use client";
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { api, dateTime } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import type { LotReport, ReplacementLinks, Shipment } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ErrorNote } from "@/components/page-header";

const pct = (n: number | null) => (n == null ? "—" : `${n}%`);

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "good" | "bad" | "warn" }) {
  const color = tone === "good" ? "text-emerald-600 dark:text-emerald-400" : tone === "bad" ? "text-destructive" : tone === "warn" ? "text-amber-600 dark:text-amber-400" : "";
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-2xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}

/** The shipment this one replaces, and the shipments that replace it, side by side (read live, so it stays current after the decision). */
function ReplacementSection({ links }: { links: ReplacementLinks }) {
  const { replaces, replaced_by: by, owed } = links;
  if (!replaces && by.length === 0) return null;
  return (
    <div className="space-y-4 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="text-xs font-medium uppercase text-muted-foreground">Replacements</div>
      {replaces && (
        <div className="space-y-2">
          <p>
            This shipment replaces <Link className="font-medium underline" href={`/shipments/${replaces.id}`}>{replaces.shipment_no}</Link>
            {replaces.items.length > 0 && <>: {replaces.items.map((d) => `${d.short} × ${d.item_code}`).join(", ")} {replaces.status === "Rejected" ? "rejected" : "faulty or missing"}</>}.
          </p>
          {replaces.units.length > 0 && (
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr><th className="py-1">Unit it replaces</th><th>Problem</th><th>Inspector&apos;s note</th></tr>
              </thead>
              <tbody>
                {replaces.units.map((u) => (
                  <tr key={u.code} className="border-t">
                    <td className="py-1"><Link className="font-mono underline" href={`/units/${u.code}`}>{u.code}</Link></td>
                    <td>{u.status === "Missing" ? "Never arrived" : u.defect_label || "Faulty"}</td>
                    <td className="text-muted-foreground">{u.notes || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {by.length > 0 && (
        <div className="space-y-2">
          <table className="w-full text-left">
            <thead className="text-xs text-muted-foreground">
              <tr><th className="py-1">Replaced by</th><th>Status</th><th>Shipped</th><th>Accepted</th><th>Quality accuracy</th></tr>
            </thead>
            <tbody>
              {by.map((b) => (
                <tr key={b.id} className="border-t">
                  <td className="py-1"><Link className="font-medium underline" href={`/shipments/${b.id}`}>{b.shipment_no}</Link></td>
                  <td>{b.status}</td>
                  <td>{b.shipped}</td>
                  <td>{b.accepted ?? "—"}</td>
                  <td>{pct(b.quality_accuracy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {owed.length > 0 && (
            <table className="w-full text-left text-xs">
              <thead className="text-muted-foreground">
                <tr><th className="py-1">Item</th><th>Faulty, missing or rejected</th><th>Replaced and accepted</th><th>On the way</th><th>Still to replace</th></tr>
              </thead>
              <tbody>
                {owed.map((d) => (
                  <tr key={d.item_code} className="border-t">
                    <td className="py-1 font-mono">{d.item_code}</td>
                    <td>{d.short}</td>
                    <td>{d.replaced}</td>
                    <td>{d.on_the_way}</td>
                    <td className={d.outstanding ? "font-medium text-destructive" : "text-emerald-600"}>{d.outstanding}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

/** The delivery quality report: live while units are being tested, frozen once the lot is decided. */
export function LotReportCard({ shipmentId, version }: { shipmentId: number; version: number }) {
  const { data: r, error } = useFetch<LotReport>(`/api/shipments/${shipmentId}/report?v=${version}`);
  if (error) return <ErrorNote message={error} />;
  if (!r) return null;
  const t = r.totals;
  const acc = r.quality_accuracy;
  const tone = acc == null ? undefined : acc >= r.threshold ? "good" : "bad";
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Delivery quality report
          {r.frozen ? <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-normal">Final · {r.decided_at ? dateTime(r.decided_at) : ""}</span> : <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-normal text-amber-700 dark:text-amber-400">Live, still being tested</span>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6 text-sm">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Quality accuracy (OK ÷ received)" value={pct(acc)} tone={tone} />
          <Stat label="Fulfilment accuracy (OK ÷ shipped)" value={pct(r.fulfilment_accuracy)} tone={r.fulfilment_accuracy == null ? undefined : r.fulfilment_accuracy >= r.threshold ? "good" : "warn"} />
          <Stat label="OK units" value={t.ok} tone="good" />
          <Stat label="Faulty units" value={t.faulty} tone={t.faulty ? "bad" : undefined} />
        </div>
        <p className="text-muted-foreground">
          {t.shipped} shipped · {t.received} received · {t.missing} missing · {t.untested} still to test. Threshold {r.threshold}%.
          {r.suggestion && !r.frozen && <> <b className={r.suggestion === "approve" ? "text-emerald-600" : "text-destructive"}>The accuracy suggests: {r.suggestion}.</b></>}
        </p>
        {r.frozen && (
          <p className="rounded-md border p-3">
            <b>Decision: {r.decision === "approve" ? "Approved" : "Rejected"}</b> by {r.decided_by}.
            {r.override_reason && <> Reason for going against the suggestion: {r.override_reason}</>}
          </p>
        )}
        {!r.frozen && r.blockers.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
            {r.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Per item</div>
            <table className="w-full text-left">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="py-1">Item</th><th>Shipped</th><th>Received</th><th>OK</th><th>Faulty</th><th>Missing</th></tr>
              </thead>
              <tbody>
                {r.per_item.map((i) => (
                  <tr key={i.item_code} className="border-t"><td className="py-1 font-mono text-xs">{i.item_code}</td><td>{i.shipped}</td><td>{i.received}</td><td>{i.ok}</td><td>{i.faulty}</td><td>{i.missing}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Faulty units by defect</div>
            {r.defects.length === 0 ? <p className="text-muted-foreground">None.</p> : (
              <ul className="space-y-1">
                {r.defects.map((d) => (
                  <li key={d.defect_type} className="flex items-center gap-2">
                    <span className="w-44 shrink-0">{d.label}</span>
                    <span className="h-2 rounded bg-destructive/70" style={{ width: `${Math.max(6, (d.count / Math.max(t.faulty, 1)) * 100)}%` }} />
                    <span>{d.count}</span>
                  </li>
                ))}
              </ul>
            )}
            {r.failed_checks.length > 0 && <p className="mt-2 text-muted-foreground">Standard checks failed: {r.failed_checks.map((c) => `${c.label} (${c.count})`).join(", ")}.</p>}
          </div>
        </div>

        {r.fields.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Test fields added during inspection</div>
            <table className="w-full text-left">
              <thead className="text-xs text-muted-foreground">
                <tr><th className="py-1">Field</th><th>Tolerance</th><th>Recorded</th><th>Passed</th><th>Failed</th><th>Min / avg / max</th></tr>
              </thead>
              <tbody>
                {r.fields.map((f) => (
                  <tr key={f.id} className="border-t">
                    <td className="py-1">{f.label}{f.required && <span className="ml-1 text-xs text-muted-foreground">(required)</span>}</td>
                    <td>{f.tolerance || "—"}</td>
                    <td>{f.recorded} of {f.units}</td>
                    <td>{f.passed}</td>
                    <td className={f.failed ? "text-destructive" : ""}>{f.failed}</td>
                    <td>{f.min != null ? `${f.min} / ${f.average} / ${f.max} ${f.unit_label}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {r.replacement && <ReplacementSection links={r.replacement} />}

        {r.faulty_units.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-medium uppercase text-muted-foreground">Faulty units</div>
            <div className="max-h-72 overflow-y-auto rounded-md border">
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-card text-xs text-muted-foreground">
                  <tr><th className="p-2">Unit</th><th>Defect</th><th>Details</th></tr>
                </thead>
                <tbody>
                  {r.faulty_units.map((u) => (
                    <tr key={u.code} className="border-t align-top">
                      <td className="p-2"><Link className="font-mono text-xs underline" href={`/units/${u.code}`}>{u.code}</Link></td>
                      <td>{u.defect_label}</td>
                      <td className="pr-2">
                        {[...u.failed_checks, ...u.failed_fields.map((f) => `${f.label} ${f.value}${f.unit_label ? " " + f.unit_label : ""} (allowed ${f.tolerance || "pass"})`)].join("; ")}
                        {u.notes && <div className="text-muted-foreground">{u.notes}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Approve or reject a lot that was inspected unit by unit. The accuracy suggests; the inspector confirms. */
export function UnitDecisionCard({ s, version, onDone }: { s: Shipment; version: number; onDone: () => void }) {
  const { data: r } = useFetch<LotReport>(`/api/shipments/${s.id}/report?v=${version}`);
  const [notes, setNotes] = useState("");
  const [override, setOverride] = useState("");
  const [reason, setReason] = useState("");
  const [improvement, setImprovement] = useState("");
  const [busy, setBusy] = useState(false);
  if (!r) return null;

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    try {
      await api(`/api/shipments/${s.id}/inspection`, { body: { decision, notes, reason, improvement, override_reason: override } });
      toast.success(decision === "approve" ? "Approved. OK units were released to stock." : "Rejected. The supplier has been asked to improve and replace.");
      onDone();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not decide");
    } finally {
      setBusy(false);
    }
  }
  const t = r.totals;
  const against = (d: "approve" | "reject") => r.suggestion != null && r.suggestion !== d;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Lot decision</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {!r.ready ? (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">Test every received unit first: {r.blockers.join("; ")}.</p>
        ) : (
          <p className="rounded-md border px-3 py-2">
            Quality accuracy <b>{pct(r.quality_accuracy)}</b> against a {r.threshold}% threshold suggests <b className={r.suggestion === "approve" ? "text-emerald-600" : "text-destructive"}>{r.suggestion}</b>. Approving releases {t.ok} OK unit(s) to stock
            {t.faulty > 0 && <> and quarantines {t.faulty} faulty unit(s); the supplier replaces only those</>}.
          </p>
        )}
        <Textarea aria-label="Inspection notes" placeholder="Inspection notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        {r.ready && (against("approve") || against("reject")) && (
          <div className="space-y-1">
            <Input aria-label="Override reason" placeholder="Reason for going against the suggestion (required then)" value={override} onChange={(e) => setOverride(e.target.value)} maxLength={500} />
            <p className="text-xs text-muted-foreground">Needed only if you {r.suggestion === "approve" ? "reject" : "approve"} although the accuracy suggests {r.suggestion}.</p>
          </div>
        )}
        <div className="flex flex-wrap items-start gap-6">
          <Button disabled={busy || !r.ready || (against("approve") && override.trim().length < 3)} onClick={() => decide("approve")}>
            Approve and release {t.ok} unit(s)
          </Button>
          <div className="min-w-64 flex-1 space-y-2">
            <Input aria-label="Rejection reason" placeholder="Rejection reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
            <Textarea aria-label="What the supplier must improve" placeholder="What must the supplier fix or improve? (sent to them)" value={improvement} onChange={(e) => setImprovement(e.target.value)} maxLength={1000} />
            <Button variant="destructive" disabled={busy || !r.ready || reason.trim().length < 3 || (against("reject") && override.trim().length < 3)} onClick={() => decide("reject")}>
              Reject the whole lot: quarantine and hold invoice
            </Button>
            <p className="text-xs text-muted-foreground">Rejecting needs at least one photo (add one on a unit or in the Files card).</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
