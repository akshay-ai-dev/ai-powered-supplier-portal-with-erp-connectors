"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, money } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { InventoryItem, POItem, PurchaseOrder, Supplier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote, PageHeader } from "@/components/page-header";

const selectCls = "h-9 w-full rounded-md border bg-background px-3 text-sm";

export default function NewPurchaseOrderPage() {
  const { user } = useAuth();
  const router = useRouter();
  const suppliers = useFetch<Supplier[]>(user?.role === "supplier" ? null : "/api/suppliers");
  const inventory = useFetch<InventoryItem[]>(user?.role === "supplier" ? null : "/api/inventory");
  const [supplierId, setSupplierId] = useState("");
  const [items, setItems] = useState<{ item_code: string; quantity: string; unit_price: string }[]>([
    { item_code: "", quantity: "1", unit_price: "0" },
  ]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user && user.role !== "buyer" && user.role !== "admin") return <ErrorNote message="Only buyers can create purchase orders." />;

  const update = (i: number, patch: Partial<(typeof items)[number]>) => setItems(items.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  const total = items.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.unit_price) || 0), 0);

  async function save(submit: boolean) {
    setError(null);
    if (!supplierId) return setError("Choose a supplier.");
    const payload: POItem[] = items.map((it) => ({ item_code: it.item_code, quantity: Number(it.quantity), unit_price: Number(it.unit_price) }));
    if (payload.some((p) => !p.item_code || !(p.quantity > 0) || p.unit_price < 0)) return setError("Every line needs an item, a quantity above 0 and a valid price.");
    setBusy(true);
    try {
      const po = await api<PurchaseOrder>("/api/purchase-orders", { body: { supplier_id: Number(supplierId), items: payload, submit } });
      toast.success(`${po.po_number} created as ${po.status}`);
      router.push(`/purchase-orders/${po.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="New purchase order" />
      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="max-w-sm space-y-2">
            <Label htmlFor="supplier">Supplier</Label>
            <select id="supplier" className={selectCls} value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Select supplier…</option>
              {suppliers.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.supplier_name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-3">
            <Label>Items</Label>
            {items.map((it, i) => (
              <div key={i} className="grid grid-cols-[1fr_90px_110px_auto] items-center gap-2 rounded-md">
                <select aria-label="Item" className={selectCls} value={it.item_code} onChange={(e) => update(i, { item_code: e.target.value })}>
                  <option value="">Select item…</option>
                  {inventory.data?.map((inv) => (
                    <option key={inv.id} value={inv.item_code}>
                      {inv.item_code} · {inv.description}
                    </option>
                  ))}
                </select>
                <Input aria-label="Quantity" type="number" min={1} value={it.quantity} onChange={(e) => update(i, { quantity: e.target.value })} />
                <Input aria-label="Unit price" type="number" min={0} step="0.01" value={it.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} />
                <Button variant="ghost" size="icon" aria-label="Remove line" disabled={items.length === 1} onClick={() => setItems(items.filter((_, idx) => idx !== i))}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setItems([...items, { item_code: "", quantity: "1", unit_price: "0" }])}>
              <Plus className="mr-1 size-4" />
              Add line
            </Button>
          </div>
          <div className="text-right text-lg font-semibold">Total: {money(total)}</div>
          <ErrorNote message={error} />
          <div className="flex justify-end gap-2">
            <Button variant="outline" disabled={busy} onClick={() => save(false)}>
              Save as draft
            </Button>
            <Button disabled={busy} onClick={() => save(true)}>
              Submit for approval
            </Button>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
