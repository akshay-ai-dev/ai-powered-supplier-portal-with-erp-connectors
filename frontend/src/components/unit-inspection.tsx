"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Download, Plus, SlidersHorizontal, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, downloadFile, uploadFile } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import type { Shipment, UnitBrief, UnitFull, UnitList } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorNote } from "@/components/page-header";
import { QrScanner } from "@/components/qr-scanner";
import { StatusBadge } from "@/components/status-badge";
import { AddFieldDialog, SetFieldDialog } from "@/components/unit-field-dialogs";
import { TestDialog } from "@/components/unit-test-dialog";
import { formatValue, msg, selectCls } from "@/components/unit-common";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- the unit list
const PAGE = 50;

export function UnitInspection({ s, inspector, version, onChanged, openCode }: { s: Shipment; inspector: boolean; version: number; onChanged: () => void; openCode?: string | null }) {
  const [status, setStatus] = useState("");
  const [item, setItem] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [testing, setTesting] = useState<string | null>(openCode ?? null);
  const [startFaulty, setStartFaulty] = useState(false);
  const [addField, setAddField] = useState(false);
  const [setField, setSetField] = useState(false);
  const [csvError, setCsvError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState(0);
  const list = useFetch<UnitList>(`/api/shipments/${s.id}/units?status=${status}&item_code=${item}&q=${encodeURIComponent(q)}&limit=${PAGE}&offset=${page * PAGE}&v=${version}-${local}`);
  const d = list.data;
  const open = inspector && s.status === "Arrived";
  const counts = d?.counts ?? {};
  const received = (counts.Received ?? 0) + (counts.OK ?? 0) + (counts.Faulty ?? 0);
  const tested = (counts.OK ?? 0) + (counts.Faulty ?? 0);

  useEffect(() => {
    if (openCode) setTesting(openCode);
  }, [openCode]);

  const refresh = () => {
    setLocal((n) => n + 1);
    onChanged();
  };

  async function run<T>(fn: () => Promise<T>, ok: (r: T) => string) {
    setBusy(true);
    try {
      toast.success(ok(await fn()));
      setSelected([]);
      refresh();
    } catch (e) {
      toast.error(msg(e));
    } finally {
      setBusy(false);
    }
  }

  type BulkResult = { updated: number; skipped_count: number; skipped: { code: string; reason: string }[] };
  const bulkOk = (body: object) =>
    run(
      () => api<BulkResult>(`/api/shipments/${s.id}/units/bulk`, { body: { action: "ok", ...body } }),
      (r) => `${r.updated} unit(s) tagged OK` + (r.skipped_count ? `, ${r.skipped_count} skipped: ${r.skipped[0]?.reason}` : ""),
    );

  async function quickOk(u: UnitBrief) {
    try {
      await api(`/api/shipments/${s.id}/units/${encodeURIComponent(u.code)}`, { method: "PUT", body: { result: "OK" } });
      refresh();
    } catch (e) {
      toast.error(msg(e));
      setStartFaulty(false);
      setTesting(u.code);
    }
  }

  async function onScan(code: string) {
    try {
      const u = await api<UnitFull>(`/api/units/${encodeURIComponent(code)}`);
      if (u.shipment.id !== s.id) return toast.error(`${u.code} belongs to shipment ${u.shipment.shipment_no}, not this one`);
      if (!["Received", "OK", "Faulty"].includes(u.status)) return toast.error(`${u.code} is ${u.status} and cannot be tested`);
      setStartFaulty(false);
      setTesting(u.code);
    } catch (e) {
      toast.error(msg(e));
    }
  }

  async function importCsv(f: File) {
    setCsvError(null);
    setBusy(true);
    try {
      const r = await uploadFile<{ updated: number }>(`/api/shipments/${s.id}/units/import`, f);
      toast.success(`${r.updated} unit(s) updated from the CSV`);
      refresh();
    } catch (e) {
      setCsvError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  const pages = d ? Math.max(1, Math.ceil(d.total / PAGE)) : 1;
  const toggleAll = () => setSelected(selected.length === (d?.units.length ?? 0) ? [] : (d?.units ?? []).filter((u) => u.status === "Received").map((u) => u.code));

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Unit inspection</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="mb-1 flex flex-wrap justify-between gap-2 text-sm">
            <span>
              <b>{tested}</b> of {received} received units tested
            </span>
            <span className="text-muted-foreground">
              {counts.OK ?? 0} OK · {counts.Faulty ?? 0} faulty · {counts.Received ?? 0} to test{counts.Missing ? ` · ${counts.Missing} missing` : ""}
            </span>
          </div>
          <div className="flex h-2 overflow-hidden rounded bg-muted">
            <div className="bg-emerald-500" style={{ width: `${received ? ((counts.OK ?? 0) / received) * 100 : 0}%` }} />
            <div className="bg-destructive" style={{ width: `${received ? ((counts.Faulty ?? 0) / received) * 100 : 0}%` }} />
          </div>
        </div>

        {open && <QrScanner onScan={onScan} placeholder="Scan a unit's QR code to test it" />}

        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Filter by status" className={selectCls} value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
            <option value="">All statuses</option>
            <option value="Received">To test</option>
            <option value="OK">OK</option>
            <option value="Faulty">Faulty</option>
            <option value="Missing">Missing</option>
          </select>
          {(d?.items.length ?? 0) > 1 && (
            <select aria-label="Filter by item" className={selectCls} value={item} onChange={(e) => { setItem(e.target.value); setPage(0); }}>
              <option value="">All items</option>
              {d?.items.map((i) => (
                <option key={i} value={i}>
                  {i}
                </option>
              ))}
            </select>
          )}
          <Input aria-label="Search unit codes" className="w-44" placeholder="Search code…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
          <span className="ml-auto flex flex-wrap gap-2">
            {open && (
              <>
                <Button size="sm" variant="outline" onClick={() => setAddField(true)}>
                  <Plus className="mr-1 size-4" />
                  Add test field
                </Button>
                {(d?.fields.length ?? 0) > 0 && (
                  <Button size="sm" variant="outline" onClick={() => setSetField(true)}>
                    <SlidersHorizontal className="mr-1 size-4" />
                    Set field value…
                  </Button>
                )}
                <Button size="sm" variant="outline" disabled={busy || selected.length === 0} onClick={() => bulkOk({ codes: selected })}>
                  Mark selected OK ({selected.length})
                </Button>
                <Button size="sm" disabled={busy || !(counts.Received ?? 0)} onClick={() => window.confirm(`Tag all ${counts.Received} untested unit(s) OK?`) && bulkOk({ all_pending: true })}>
                  Mark all remaining OK
                </Button>
              </>
            )}
            <Button size="sm" variant="outline" onClick={() => downloadFile(`/api/shipments/${s.id}/units.csv`, `${s.shipment_no}-units.csv`).catch((e) => toast.error(msg(e)))}>
              <Download className="mr-1 size-4" />
              CSV
            </Button>
            {open && (
              <label className="inline-flex">
                <span className="sr-only">Upload results CSV</span>
                <input type="file" accept=".csv,text/csv" disabled={busy} className="hidden" id="csv-up" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void importCsv(f); }} />
                <Button size="sm" variant="outline" type="button" disabled={busy} onClick={() => document.getElementById("csv-up")?.click()}>
                  <Upload className="mr-1 size-4" />
                  Upload results
                </Button>
              </label>
            )}
          </span>
        </div>
        {csvError && <p role="alert" className="whitespace-pre-wrap rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{csvError}</p>}
        <ErrorNote message={list.error} />

        <div className="max-h-[32rem] overflow-auto rounded-md border">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 z-10 bg-card text-xs text-muted-foreground">
              <tr>
                {open && (
                  <th className="w-8 p-2">
                    <input type="checkbox" aria-label="Select all to-test units on this page" checked={selected.length > 0 && selected.length === (d?.units ?? []).filter((u) => u.status === "Received").length} onChange={toggleAll} />
                  </th>
                )}
                <th className="p-2">Unit</th>
                <th>Status</th>
                <th>Defect</th>
                {d?.fields.map((f) => (
                  <th key={f.id} title={f.tolerance ? `Allowed ${f.tolerance}` : undefined}>
                    {f.label}
                    {f.unit_label ? ` (${f.unit_label})` : ""}
                  </th>
                ))}
                <th className="pr-2 text-right">Test</th>
              </tr>
            </thead>
            <tbody>
              {d?.units.map((u) => {
                const testable = open && ["Received", "OK", "Faulty"].includes(u.status);
                return (
                  <tr key={u.code} className="border-t">
                    {open && (
                      <td className="p-2">
                        {u.status === "Received" && (
                          <input type="checkbox" aria-label={`Select ${u.code}`} checked={selected.includes(u.code)} onChange={() => setSelected(selected.includes(u.code) ? selected.filter((c) => c !== u.code) : [...selected, u.code])} />
                        )}
                      </td>
                    )}
                    <td className="p-2">
                      <Link href={`/units/${encodeURIComponent(u.code)}`} className="font-mono text-xs underline">
                        {u.code}
                      </Link>
                    </td>
                    <td>
                      <StatusBadge status={u.status === "Received" ? "Received" : u.status} />
                    </td>
                    <td className="text-xs">{u.defect_label}</td>
                    {d.fields.map((f) => {
                      const applies = !f.item_code || f.item_code.toUpperCase() === u.item_code.toUpperCase();
                      const res = u.field_results[String(f.id)];
                      return (
                        <td key={f.id} className={cn("text-xs", res === "fail" && "font-medium text-destructive")}>
                          {applies ? formatValue(f, u.readings[String(f.id)]) : ""}
                        </td>
                      );
                    })}
                    <td className="space-x-1 whitespace-nowrap pr-2 text-right">
                      {testable ? (
                        <>
                          <Button size="sm" variant="outline" disabled={u.status === "OK"} onClick={() => quickOk(u)}>
                            OK
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => { setStartFaulty(true); setTesting(u.code); }}>
                            Faulty
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => { setStartFaulty(false); setTesting(u.code); }}>
                            Details
                          </Button>
                        </>
                      ) : (
                        <Link href={`/units/${encodeURIComponent(u.code)}`} className="text-xs underline">
                          Report
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
              {d && d.units.length === 0 && (
                <tr>
                  <td colSpan={8 + (d.fields.length ?? 0)} className="p-4 text-center text-muted-foreground">
                    No units match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {d && d.total > PAGE && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {page * PAGE + 1}-{Math.min((page + 1) * PAGE, d.total)} of {d.total}
            </span>
            <span className="flex gap-2">
              <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
              <Button size="sm" variant="outline" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </span>
          </div>
        )}
      </CardContent>

      <TestDialog shipmentId={s.id} code={testing} fields={d?.fields ?? []} startFaulty={startFaulty} onClose={() => setTesting(null)} onSaved={refresh} />
      <AddFieldDialog s={s} items={d?.items ?? []} open={addField} onClose={() => setAddField(false)} onDone={refresh} />
      <SetFieldDialog s={s} fields={d?.fields ?? []} selected={selected} open={setField} onClose={() => setSetField(false)} onDone={refresh} />
    </Card>
  );
}
