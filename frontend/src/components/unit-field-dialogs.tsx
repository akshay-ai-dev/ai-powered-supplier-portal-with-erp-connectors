"use client";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { FieldType, Shipment, TestField } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/page-header";
import { msg, selectCls } from "@/components/unit-common";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- add a test field
export function AddFieldDialog({ s, items, open, onClose, onDone }: { s: Shipment; items: string[]; open: boolean; onClose: () => void; onDone: () => void }) {
  const blank = { label: "", type: "number" as FieldType, unit_label: "", min_value: "", max_value: "", required: false, item_code: "", save_template: false };
  const [f, setF] = useState(blank);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/api/shipments/${s.id}/fields`, {
        body: {
          label: f.label,
          type: f.type,
          unit_label: f.unit_label,
          min_value: f.type === "number" && f.min_value !== "" ? Number(f.min_value) : null,
          max_value: f.type === "number" && f.max_value !== "" ? Number(f.max_value) : null,
          required: f.required,
          item_code: f.item_code || null,
          save_template: f.save_template,
        },
      });
      toast.success(`Test field "${f.label}" added to every unit`);
      setF(blank);
      onDone();
      onClose();
    } catch (err) {
      setError(msg(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <form onSubmit={save} className="space-y-3">
          <DialogHeader>
            <DialogTitle>Add a test field</DialogTitle>
            <DialogDescription>Every unit gets this field next to the standard checks. Values already tested stay as they are.</DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="tf-label">Name</Label>
            <Input id="tf-label" required maxLength={80} placeholder="e.g. Voltage, Weight, Seal intact" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="tf-type">Type</Label>
              <select id="tf-type" className={cn(selectCls, "w-full")} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as FieldType })}>
                <option value="number">Number (measurement)</option>
                <option value="pass_fail">Pass / Fail</option>
                <option value="text">Text (information only)</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="tf-item">Applies to</Label>
              <select id="tf-item" className={cn(selectCls, "w-full")} value={f.item_code} onChange={(e) => setF({ ...f, item_code: e.target.value, save_template: e.target.value ? f.save_template : false })}>
                <option value="">All items</option>
                {items.map((i) => (
                  <option key={i} value={i}>
                    {i}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {f.type === "number" && (
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label htmlFor="tf-unit">Unit</Label>
                <Input id="tf-unit" maxLength={20} placeholder="V, mm, kg" value={f.unit_label} onChange={(e) => setF({ ...f, unit_label: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="tf-min">Min allowed</Label>
                <Input id="tf-min" type="number" step="any" value={f.min_value} onChange={(e) => setF({ ...f, min_value: e.target.value })} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="tf-max">Max allowed</Label>
                <Input id="tf-max" type="number" step="any" value={f.max_value} onChange={(e) => setF({ ...f, max_value: e.target.value })} />
              </div>
            </div>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.required} onChange={(e) => setF({ ...f, required: e.target.checked })} />
            Required: a unit cannot be OK without a value
          </label>
          <label className={cn("flex items-center gap-2 text-sm", !f.item_code && "text-muted-foreground")}>
            <input type="checkbox" disabled={!f.item_code} checked={f.save_template} onChange={(e) => setF({ ...f, save_template: e.target.checked })} />
            Also use it for future deliveries of {f.item_code || "this item"} (choose an item first)
          </label>
          <ErrorNote message={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !f.label.trim()}>
              Add field
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- set one field on many units
export function SetFieldDialog({ s, fields, selected, open, onClose, onDone }: { s: Shipment; fields: TestField[]; selected: string[]; open: boolean; onClose: () => void; onDone: () => void }) {
  const [fieldId, setFieldId] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const field = fields.find((f) => String(f.id) === fieldId);

  async function save() {
    setBusy(true);
    try {
      const r = await api<{ updated: number; skipped_count: number; skipped: { code: string; reason: string }[] }>(`/api/shipments/${s.id}/units/bulk`, {
        body: { action: "set_field", field_id: Number(fieldId), value, ...(selected.length ? { codes: selected } : { all_pending: true }) },
      });
      toast.success(`${r.updated} unit(s) updated` + (r.skipped_count ? `, ${r.skipped_count} skipped: ${r.skipped[0]?.reason}` : ""));
      onDone();
      onClose();
    } catch (e) {
      toast.error(msg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Set a field value on many units</DialogTitle>
          <DialogDescription>{selected.length ? `For the ${selected.length} selected unit(s).` : "For every unit of the shipment."}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <select aria-label="Test field" className={cn(selectCls, "w-full")} value={fieldId} onChange={(e) => { setFieldId(e.target.value); setValue(""); }}>
            <option value="">Choose a field…</option>
            {fields.map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
          </select>
          {field?.type === "pass_fail" ? (
            <select aria-label="Value" className={cn(selectCls, "w-full")} value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">Value…</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
            </select>
          ) : (
            <Input aria-label="Value" type={field?.type === "number" ? "number" : "text"} step="any" placeholder={field?.tolerance ? `Allowed: ${field.tolerance}` : "Value"} value={value} onChange={(e) => setValue(e.target.value)} />
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || !fieldId || !value} onClick={save}>
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
