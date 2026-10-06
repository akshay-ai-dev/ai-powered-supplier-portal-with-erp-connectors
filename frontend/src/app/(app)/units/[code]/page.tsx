"use client";
import Link from "next/link";
import { use, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Download } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime, downloadFile, fileSize } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import { useAuth } from "@/lib/auth";
import { roleLabel } from "@/lib/roles";
import { decodeSegment } from "@/lib/units";
import type { TestField, UnitFull } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AgentBadge } from "@/components/agent-badge";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { TestDialog } from "@/components/unit-test-dialog";

const ACTIONS: Record<string, string> = { receive: "Scanned at arrival", unreceive: "Scan undone", test: "Tested", readings: "Readings saved" };

/** Everything known about one unit, found by its QR code. */
export default function UnitDetailPage({ params }: { params: Promise<{ code: string }> }) {
  const code = decodeSegment(use(params).code);
  const { user } = useAuth();
  const [version, setVersion] = useState(0);
  const query = useSearchParams();
  const [testing, setTesting] = useState(query?.get("inspect") === "1");
  const [startFaulty, setStartFaulty] = useState(false);
  const [busy, setBusy] = useState(false);
  const { data: u, error, loading } = useFetch<UnitFull>(`/api/units/${encodeURIComponent(code)}?v=${version}`);
  const fields = useFetch<TestField[]>(u?.can_test ? `/api/shipments/${u.shipment.id}/fields` : null);
  const refresh = () => setVersion((n) => n + 1);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  if (loading && u?.code.toLowerCase() !== code.toLowerCase()) return <p className="text-sm text-muted-foreground">Loading…</p>; // a refresh after saving keeps the page (and an open dialog) in place
  if (error || !u) return <ErrorNote message={error ?? "Not found"} />;

  return (
    <>
      <Link href={`/shipments/${u.shipment.id}`} className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="mr-1 size-4" />
        {u.shipment.shipment_no}
      </Link>
      <PageHeader title={u.code} description={`${u.item_code} · shipment ${u.shipment.shipment_no} · order ${u.shipment.po_number} · ${u.shipment.supplier_name ?? ""}`}>
        <StatusBadge status={u.status} />
      </PageHeader>

      {(u.can_receive || u.can_test) && (
        <Card className="mb-6 border-primary/40">
          <CardHeader>
            <CardTitle>Inspect this unit</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2 text-sm">
            {u.can_receive ? (
              <>
                <span className="text-muted-foreground">
                  {u.status === "Missing"
                    ? "This unit was not scanned when arrival was confirmed, so it counts as missing. If it is here, mark it present, then test it."
                    : "The shipment has not been confirmed as arrived yet. Scanning counts this unit as received."}
                </span>
                <Button disabled={busy} onClick={() => act(() => api(`/api/shipments/${u.shipment.id}/units/${encodeURIComponent(u.code)}/receive`, { method: "POST" }), u.status === "Missing" ? "Marked present" : "Received")}>
                  {u.status === "Missing" ? "Mark as present" : "Receive this unit"}
                </Button>
              </>
            ) : (
              <>
                <Button disabled={busy || u.status === "OK"} onClick={() => act(() => api(`/api/shipments/${u.shipment.id}/units/${encodeURIComponent(u.code)}`, { method: "PUT", body: { result: "OK" } }), "Tagged OK")}>
                  Tag OK
                </Button>
                <Button variant="destructive" onClick={() => { setStartFaulty(true); setTesting(true); }}>
                  Faulty
                </Button>
                <Button variant="outline" onClick={() => { setStartFaulty(false); setTesting(true); }}>
                  Checks, test fields, photo, notes
                </Button>
                <Link href={`/shipments/${u.shipment.id}`} className="ml-auto text-xs underline">
                  Open the whole shipment
                </Link>
              </>
            )}
          </CardContent>
        </Card>
      )}
      {!u.can_test && !u.can_receive && u.shipment.status === "Arrived" && (
        <p className="mb-6 text-sm text-muted-foreground">
          You are signed in as {user?.name ?? "a user"} ({user ? roleLabel(user) : ""}), which can view this unit but not inspect it. Only an inspector can.
          {user?.role === "buyer" && <> Add one under <Link className="underline" href="/team">My inspectors</Link>, then sign in as that inspector and scan the code again.</>}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Test record</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <ul className="space-y-1">
              {u.checks.map((c) => (
                <li key={c.key} className="flex items-center gap-2">
                  <span className={c.passed === true ? "text-emerald-600" : c.passed === false ? "text-destructive" : "text-muted-foreground"}>{c.passed === true ? "✓ Passed" : c.passed === false ? "✗ Failed" : "– Not recorded"}</span>
                  <span>{c.label}</span>
                </li>
              ))}
            </ul>
            {u.field_values.length > 0 && (
              <div className="border-t pt-3">
                <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">Test fields</div>
                <ul className="space-y-1">
                  {u.field_values.map((f) => (
                    <li key={f.field_id} className="flex flex-wrap items-center gap-2">
                      <span className={f.result === "fail" ? "text-destructive" : f.result === "pass" ? "text-emerald-600" : "text-muted-foreground"}>{f.result === "fail" ? "✗" : f.result === "pass" ? "✓" : "–"}</span>
                      <span>{f.label}:</span>
                      <b>{f.value == null ? "not recorded" : f.type === "pass_fail" ? (f.value === "pass" ? "Pass" : "Fail") : `${f.value}${f.unit_label ? " " + f.unit_label : ""}`}</b>
                      {f.tolerance && <span className="text-xs text-muted-foreground">allowed {f.tolerance}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {u.status === "Faulty" && (
              <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2">
                <b>Defect:</b> {u.defect_label}
              </p>
            )}
            {u.notes && <p className="whitespace-pre-wrap"><span className="text-muted-foreground">Notes: </span>{u.notes}</p>}
            <div className="grid grid-cols-2 gap-2 border-t pt-3 text-xs text-muted-foreground">
              <div>Received: {u.received_at ? `${dateTime(u.received_at)} by ${u.received_by ?? "?"}` : "—"}</div>
              <div>Tested: {u.tested_at ? `${dateTime(u.tested_at)} by ${u.tested_by ?? "?"}` : "—"}</div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Photos</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {u.photos.length === 0 && <p className="text-muted-foreground">None.</p>}
              {u.photos.map((p) => (
                <div key={p.id} className="flex items-center justify-between gap-2">
                  <span className="truncate">{p.filename} <span className="text-xs text-muted-foreground">({fileSize(p.size)})</span></span>
                  <Button variant="ghost" size="icon" aria-label={`Download ${p.filename}`} onClick={() => downloadFile(`/api/shipment-files/${p.id}/download`, p.filename).catch((e) => toast.error(e.message))}>
                    <Download className="size-4" />
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>History</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {u.history.length === 0 && <p className="text-muted-foreground">No activity yet.</p>}
              {u.history.map((h, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2">
                  <b>{ACTIONS[h.action] ?? h.action}</b>
                  {h.detail && <span className="text-muted-foreground">{h.detail}</span>}
                  <AgentBadge channel={h.channel} compact />
                  <span className="ml-auto text-xs text-muted-foreground">{h.user_name} · {dateTime(h.created_at)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
      <TestDialog shipmentId={u.shipment.id} code={testing ? u.code : null} fields={fields.data ?? []} startFaulty={startFaulty} onClose={() => setTesting(false)} onSaved={refresh} />
    </>
  );
}
