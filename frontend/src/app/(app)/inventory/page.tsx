"use client";
import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, shortDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { InventoryItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

function Stock({ qty }: { qty: number }) {
  if (qty === 0) return <Badge variant="destructive">Out of stock</Badge>;
  if (qty < 20) return <Badge variant="outline" className="border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400">Low · {qty}</Badge>;
  return <span>{qty.toLocaleString()}</span>;
}

const EMPTY = { item_code: "", description: "", stock_quantity: "0", warehouse: "MAIN" };

export default function InventoryPage() {
  const { user } = useAuth();
  const canWrite = user?.role === "buyer" || user?.role === "admin" || user?.role === "supplier"; // each manages their own items
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, error, loading, reload } = useFetch<InventoryItem[]>(`/api/inventory?q=${encodeURIComponent(debounced)}`);

  const [form, setForm] = useState<typeof EMPTY | null>(null); // null = form closed
  const [editing, setEditing] = useState<string | null>(null); // item_code being edited
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form!, [k]: e.target.value });

  function openAdd() {
    setEditing(null);
    setFormError(null);
    setForm(EMPTY);
  }
  function openEdit(i: InventoryItem) {
    setEditing(i.item_code);
    setFormError(null);
    setForm({ item_code: i.item_code, description: i.description, stock_quantity: String(i.stock_quantity), warehouse: i.warehouse });
  }

  async function remove(i: InventoryItem) {
    if (!window.confirm(`Delete ${i.item_code} (${i.description})? This cannot be undone.`)) return;
    try {
      await api(`/api/inventory/${encodeURIComponent(i.item_code)}`, { method: "DELETE" });
      toast.success(`${i.item_code} deleted`);
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setFormError(null);
    try {
      const body = { description: form.description, stock_quantity: Number(form.stock_quantity), warehouse: form.warehouse };
      if (editing) await api(`/api/inventory/${encodeURIComponent(editing)}`, { method: "PUT", body });
      else await api("/api/inventory", { body: { item_code: form.item_code, ...body } });
      toast.success(editing ? `${editing} updated` : "Item added");
      setForm(null);
      await reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Inventory" description="Stock availability across warehouses.">
        <Input className="w-64" placeholder="Search item code or description…" value={q} onChange={(e) => setQ(e.target.value)} />
        {canWrite && (
          <Button onClick={openAdd}>
            <Plus className="mr-1 size-4" />
            Add item
          </Button>
        )}
      </PageHeader>

      {form && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>{editing ? `Edit ${editing}` : "Add inventory item"}</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={save} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end">
              <div className="space-y-1">
                <Label htmlFor="ic">Item code</Label>
                <Input id="ic" required disabled={!!editing} value={form.item_code} onChange={set("item_code")} placeholder="ITEM009" />
              </div>
              <div className="space-y-1 lg:col-span-2">
                <Label htmlFor="id">Description</Label>
                <Input id="id" required value={form.description} onChange={set("description")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="is">Stock</Label>
                <Input id="is" type="number" min={0} required value={form.stock_quantity} onChange={set("stock_quantity")} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="iw">Warehouse</Label>
                <Input id="iw" required value={form.warehouse} onChange={set("warehouse")} />
              </div>
              <div className="flex gap-2 sm:col-span-2 lg:col-span-5">
                <Button type="submit" disabled={busy}>
                  {editing ? "Save changes" : "Add item"}
                </Button>
                <Button type="button" variant="outline" onClick={() => setForm(null)}>
                  Cancel
                </Button>
              </div>
              {formError && (
                <div className="sm:col-span-2 lg:col-span-5">
                  <ErrorNote message={formError} />
                </div>
              )}
            </form>
          </CardContent>
        </Card>
      )}

      <ErrorNote message={error} />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item code</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Stock</TableHead>
              <TableHead className="hidden sm:table-cell">Warehouse</TableHead>
              <TableHead className="hidden md:table-cell">ERP</TableHead>
              <TableHead className="hidden md:table-cell">Updated</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  No items match.
                </TableCell>
              </TableRow>
            )}
            {data?.map((i) => (
              <TableRow key={i.id}>
                <TableCell className="font-mono text-xs">{i.item_code}</TableCell>
                <TableCell>{i.description}</TableCell>
                <TableCell>
                  <Stock qty={i.stock_quantity} />
                </TableCell>
                <TableCell className="hidden sm:table-cell">{i.warehouse}</TableCell>
                <TableCell className="hidden uppercase md:table-cell">{i.source}</TableCell>
                <TableCell className="hidden md:table-cell">{shortDate(i.updated_at)}</TableCell>
                <TableCell className="text-right">
                  {i.can_edit && (
                    <Button variant="ghost" size="icon" aria-label={`Edit ${i.item_code}`} onClick={() => openEdit(i)}>
                      <Pencil className="size-4" />
                    </Button>
                  )}
                  {i.can_delete && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${i.item_code}`}
                      disabled={!!i.in_use}
                      title={i.in_use ? `Used by ${i.in_use} PO line(s) or requirement(s)` : "Delete item"}
                      onClick={() => remove(i)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
