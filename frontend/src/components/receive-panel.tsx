"use client";
import { useState } from "react";
import { Check, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import type { Shipment, UnitList } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { QrScanner } from "@/components/qr-scanner";
import { msg } from "@/components/unit-common";

// ---------------------------------------------------------------- receive by scanning
export function ReceivePanel({ s, version, onChanged }: { s: Shipment; version: number; onChanged: () => void }) {
  const list = useFetch<UnitList>(`/api/shipments/${s.id}/units?status=Shipped&limit=30&v=${version}`);
  const [scans, setScans] = useState<{ code: string; ok: boolean; text: string }[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const counts = list.data?.counts ?? {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const scanned = counts.Received ?? 0;
  const left = counts.Shipped ?? 0;

  async function onScan(code: string) {
    try {
      await api(`/api/shipments/${s.id}/units/${encodeURIComponent(code)}/receive`, { method: "POST" });
      setScans((l) => [{ code, ok: true, text: "Received" }, ...l].slice(0, 8));
    } catch (e) {
      setScans((l) => [{ code, ok: false, text: msg(e) }, ...l].slice(0, 8));
    }
    await list.reload();
  }

  async function undo(code: string) {
    try {
      await api(`/api/shipments/${s.id}/units/${encodeURIComponent(code)}/unreceive`, { method: "POST" });
      setScans((l) => l.filter((x) => x.code !== code));
      await list.reload();
    } catch (e) {
      toast.error(msg(e));
    }
  }

  async function confirm() {
    if (left > 0 && !window.confirm(`${left} unit(s) were not scanned. They will be marked missing and the supplier will be told about the shortfall. Confirm arrival?`)) return;
    setBusy(true);
    try {
      await api(`/api/shipments/${s.id}/arrival`, { body: { lines: [], notes } });
      toast.success("Arrival confirmed. Now test the units.");
      onChanged();
    } catch (e) {
      toast.error(msg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Receive by scanning</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">Scan each unit&apos;s QR code as it comes off the truck. Scanned units count as received; anything not scanned is reported as missing.</p>
        <QrScanner onScan={onScan} />
        <div>
          <div className="mb-1 flex justify-between text-sm">
            <span>
              <b>{scanned}</b> of {total} scanned
            </span>
            <span className="text-muted-foreground">{left} not scanned yet</span>
          </div>
          <div className="h-2 overflow-hidden rounded bg-muted">
            <div className="h-full bg-emerald-500" style={{ width: `${total ? (scanned / total) * 100 : 0}%` }} />
          </div>
        </div>
        {scans.length > 0 && (
          <ul className="space-y-1 text-sm" aria-label="Recent scans">
            {scans.map((x, i) => (
              <li key={x.code + i} className="flex items-center gap-2">
                {x.ok ? <Check className="size-4 text-emerald-600" /> : <X className="size-4 text-destructive" />}
                <span className="font-mono text-xs">{x.code}</span>
                <span className={x.ok ? "text-muted-foreground" : "text-destructive"}>{x.text}</span>
                {x.ok && (
                  <button type="button" className="ml-auto text-xs underline" onClick={() => undo(x.code)}>
                    Undo
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {left > 0 && list.data && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">Not scanned yet ({left})</summary>
            <div className="mt-2 flex flex-wrap gap-1">
              {list.data.units.map((u) => (
                <span key={u.code} className="rounded border px-1.5 py-0.5 font-mono text-xs">
                  {u.code}
                </span>
              ))}
              {left > list.data.units.length && <span className="text-xs text-muted-foreground">and {left - list.data.units.length} more</span>}
            </div>
          </details>
        )}
        <Textarea aria-label="Arrival notes" placeholder="Condition on arrival, damage to packaging, etc. (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <Button disabled={busy} onClick={confirm}>
          Confirm arrival ({scanned} received)
        </Button>
      </CardContent>
    </Card>
  );
}
