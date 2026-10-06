"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { api, fileSize, uploadFile } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import { DEFECT_OPTIONS, type TestField, type UnitFull } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ErrorNote } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { judge, msg, selectCls } from "@/components/unit-common";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- test one unit
export function TestDialog({ shipmentId, code, fields, startFaulty, onClose, onSaved }: { shipmentId: number; code: string | null; fields: TestField[]; startFaulty: boolean; onClose: () => void; onSaved: () => void }) {
  const [version, setVersion] = useState(0);
  const { data: unit, error } = useFetch<UnitFull>(code ? `/api/units/${encodeURIComponent(code)}?v=${version}` : null);
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [readings, setReadings] = useState<Record<string, string>>({});
  const [defect, setDefect] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const loaded = useRef<string | null>(null);

  useEffect(() => {
    if (!unit || loaded.current === unit.code + unit.status + unit.tested_at) return;
    loaded.current = unit.code + unit.status + unit.tested_at;
    setChecks(Object.fromEntries(unit.checks.map((c) => [c.key, c.passed !== false])));
    setReadings(Object.fromEntries(unit.field_values.filter((v) => !v.archived && v.value != null).map((v) => [String(v.field_id), String(v.value)])));
    setDefect(unit.defect_type || "");
    setNotes(unit.notes || "");
    setFormError(null);
  }, [unit]);

  const mine = useMemo(() => (unit ? unit.field_values.filter((v) => !v.archived) : []), [unit]);
  const byId = useMemo(() => new Map(fields.map((f) => [String(f.id), f])), [fields]);
  const verdicts = mine.map((v) => ({ v, field: byId.get(String(v.field_id)), result: judge(byId.get(String(v.field_id)) ?? { type: v.type, min_value: null, max_value: null }, readings[String(v.field_id)] ?? "") }));
  const failedField = verdicts.some((x) => x.result === "fail");
  const failedCheck = Object.values(checks).some((v) => v === false);
  const missingRequired = verdicts.some((x) => x.v.required && x.result === null);

  async function save(result: "OK" | "Faulty" | null) {
    setBusy(true);
    setFormError(null);
    try {
      await api(`/api/shipments/${shipmentId}/units/${encodeURIComponent(code!)}`, {
        method: "PUT",
        body: {
          result,
          checks: result === "OK" ? undefined : checks,
          readings: Object.fromEntries(mine.map((v) => [String(v.field_id), readings[String(v.field_id)] ?? ""])),
          defect_type: result === "Faulty" ? defect || (failedField ? "out_of_tolerance" : "") : "",
          notes,
        },
      });
      toast.success(result ? `${code} tagged ${result}` : "Readings saved");
      onSaved();
      if (result) onClose();
      else setVersion((n) => n + 1);
    } catch (e) {
      setFormError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  async function photo(f: File) {
    try {
      await uploadFile(`/api/shipments/${shipmentId}/units/${encodeURIComponent(code!)}/photo`, f);
      toast.success("Photo added");
      setVersion((n) => n + 1);
    } catch (e) {
      toast.error(msg(e));
    }
  }

  const canEdit = !!unit?.can_test;
  return (
    <Dialog open={!!code} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-mono text-base">
            {code} {unit && <StatusBadge status={unit.status} />}
          </DialogTitle>
          <DialogDescription>{unit ? `${unit.item_code} · shipment ${unit.shipment.shipment_no} · order ${unit.shipment.po_number}` : "Loading…"}</DialogDescription>
        </DialogHeader>
        <ErrorNote message={error} />
        {unit && (
          <div className="space-y-4 text-sm">
            <div className="space-y-1">
              <div className="text-xs font-medium uppercase text-muted-foreground">Standard checks</div>
              {unit.checks.map((c) => (
                <div key={c.key} className="flex items-center justify-between gap-2 rounded-md border px-3 py-1.5">
                  <span>{c.label}</span>
                  <span className="flex gap-1" role="radiogroup" aria-label={c.label}>
                    {([true, false] as const).map((v) => (
                      <button
                        key={String(v)}
                        type="button"
                        role="radio"
                        aria-checked={checks[c.key] === v}
                        disabled={!canEdit}
                        onClick={() => setChecks({ ...checks, [c.key]: v })}
                        className={cn("rounded-md border px-3 py-0.5 text-xs", checks[c.key] === v ? (v ? "border-emerald-600 bg-emerald-500/15 font-medium" : "border-destructive bg-destructive/15 font-medium") : "text-muted-foreground")}
                      >
                        {v ? "Pass" : "Fail"}
                      </button>
                    ))}
                  </span>
                </div>
              ))}
            </div>

            {mine.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs font-medium uppercase text-muted-foreground">Test fields</div>
                {verdicts.map(({ v, result }) => {
                  const id = String(v.field_id);
                  return (
                    <div key={id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-1.5">
                      <label htmlFor={`rf-${id}`}>
                        {v.label}
                        {v.required && <span className="ml-1 text-xs text-muted-foreground">(required)</span>}
                        {v.tolerance && <span className="ml-1 text-xs text-muted-foreground">allowed {v.tolerance}</span>}
                      </label>
                      <span className="flex items-center gap-2">
                        {v.type === "pass_fail" ? (
                          <select id={`rf-${id}`} disabled={!canEdit} className={cn(selectCls, "h-8 w-28")} value={readings[id] ?? ""} onChange={(e) => setReadings({ ...readings, [id]: e.target.value })}>
                            <option value="">Not recorded</option>
                            <option value="pass">Pass</option>
                            <option value="fail">Fail</option>
                          </select>
                        ) : (
                          <Input id={`rf-${id}`} disabled={!canEdit} className="w-28" type={v.type === "number" ? "number" : "text"} step="any" value={readings[id] ?? ""} onChange={(e) => setReadings({ ...readings, [id]: e.target.value })} />
                        )}
                        {v.type === "number" && v.unit_label && <span className="w-8 text-xs text-muted-foreground">{v.unit_label}</span>}
                        <span className={cn("w-12 text-xs", result === "fail" ? "text-destructive" : result === "pass" ? "text-emerald-600" : "text-muted-foreground")}>{result === "fail" ? "✗ Fail" : result === "pass" ? "✓ Pass" : "–"}</span>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="defect">Defect (when faulty)</Label>
                <select id="defect" disabled={!canEdit} className={cn(selectCls, "w-full")} value={defect || (startFaulty && failedField ? "out_of_tolerance" : "")} onChange={(e) => setDefect(e.target.value)}>
                  <option value="">Choose…</option>
                  {Object.entries(DEFECT_OPTIONS).map(([k, label]) => (
                    <option key={k} value={k}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="photo">Photo (optional)</Label>
                <Input id="photo" type="file" accept="image/*" disabled={!canEdit} onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void photo(f); }} />
              </div>
            </div>
            {unit.photos.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Photos: {unit.photos.map((p) => `${p.filename} (${fileSize(p.size)})`).join(", ")}
              </p>
            )}
            <Textarea aria-label="Notes" disabled={!canEdit} placeholder="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
            {(failedField || failedCheck) && canEdit && <p className="text-xs text-destructive">{failedField ? "A test field is out of its allowed range" : "A standard check failed"}, so this unit cannot be OK.</p>}
            <ErrorNote message={formError} />
            {canEdit ? (
              <DialogFooter className="flex-wrap gap-2">
                <Button variant="outline" disabled={busy} onClick={() => save(null)}>
                  Save readings only
                </Button>
                <Button variant="destructive" disabled={busy || (!defect && !failedField)} onClick={() => save("Faulty")}>
                  Tag Faulty
                </Button>
                <Button disabled={busy || failedField || failedCheck || missingRequired} onClick={() => save("OK")}>
                  Tag OK
                </Button>
              </DialogFooter>
            ) : unit.can_receive ? (
              <div className="flex flex-wrap items-center gap-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
                <span className="flex-1 text-xs">This unit was not scanned when arrival was confirmed, so it counts as missing. If it is here, mark it present and then test it.</span>
                <Button
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api(`/api/shipments/${shipmentId}/units/${encodeURIComponent(code!)}/receive`, { method: "POST" });
                      toast.success(`${code} marked present`);
                      onSaved();
                      setVersion((n) => n + 1);
                    } catch (e) {
                      setFormError(msg(e));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Mark as present
                </Button>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">This unit cannot be changed ({unit.status === "Missing" ? "the lot has been decided" : "the lot is not open for testing"}).</p>
            )}
            <Link href={`/units/${encodeURIComponent(unit.code)}`} className="text-xs underline">
              Open the full unit report
            </Link>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
