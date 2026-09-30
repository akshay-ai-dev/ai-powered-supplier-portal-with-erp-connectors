"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { api, fileSize, localInputToIso, toLocalInput, uploadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { InventoryItem, Requirement, Supplier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ErrorNote, PageHeader } from "@/components/page-header";

const selectCls = "h-9 w-full rounded-md border bg-background px-3 text-sm";

export default function NewRequirementPage() {
  const { user } = useAuth();
  const router = useRouter();
  const isSupplier = user?.role === "supplier";
  const inventory = useFetch<InventoryItem[]>(isSupplier ? null : "/api/inventory");
  const suppliers = useFetch<Supplier[]>(isSupplier ? null : "/api/suppliers");
  const [f, setF] = useState({ title: "", description: "", item_code: "", quantity: "1", target_price: "", needed_by: "", erp: "sap" });
  const [deadline, setDeadline] = useState(() => toLocalInput(new Date(Date.now() + 7 * 24 * 3600 * 1000)));
  const [audience, setAudience] = useState<"all" | "selected">("all");
  const [invited, setInvited] = useState<number[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user && user.role !== "buyer" && user.role !== "admin") return <ErrorNote message="Only buyers can post requirements." />;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const chosen = inventory.data?.find((i) => i.item_code === f.item_code);
  const title = chosen ? chosen.description : f.title.trim(); // one source of truth: the inventory item, or the new item's name
  const allIds = suppliers.data?.map((s) => s.id) ?? [];
  const toggle = (id: number) => setInvited(invited.includes(id) ? invited.filter((x) => x !== id) : [...invited, id]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!title) return setError("Describe the item you need.");
    if (deadline && new Date(deadline).getTime() <= Date.now()) return setError("The quote deadline must be in the future.");
    if (audience === "selected" && invited.length === 0) return setError("Select at least one supplier, or choose Open to all suppliers.");
    setBusy(true);
    let created: Requirement;
    try {
      created = await api<Requirement>("/api/requirements", {
        body: {
          title,
          description: f.description,
          item_code: f.item_code || null,
          quantity: Number(f.quantity),
          target_price: f.target_price ? Number(f.target_price) : null,
          needed_by: f.needed_by || null,
          erp: f.erp,
          quote_deadline: localInputToIso(deadline),
          open_to_all: audience === "all",
          supplier_ids: audience === "all" ? [] : invited,
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
      setBusy(false);
      return;
    }
    // The requirement exists now; upload files one by one and report any that fail instead of losing the requirement.
    const failed: string[] = [];
    for (const file of files) {
      try {
        await uploadFile(`/api/requirements/${created.id}/attachments`, file);
      } catch (err) {
        failed.push(`${file.name}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    toast.success(`${created.req_number} posted to ${audience === "all" ? "all suppliers" : `${invited.length} supplier(s)`}.`);
    if (failed.length) toast.error(`Some files were not attached. ${failed.join("; ")}. You can add them on the next page.`);
    router.push(`/requirements/${created.id}`);
  }

  return (
    <>
      <PageHeader title="New requirement" description="Open it to every supplier, or invite specific ones. Only they can see it and respond with a quote." />
      <Card className="max-w-2xl">
        <CardContent className="pt-6">
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="item">Item</Label>
              <select id="item" value={f.item_code} onChange={set("item_code")} className={selectCls}>
                <option value="">New item (not in inventory)</option>
                {inventory.data?.map((i) => (
                  <option key={i.id} value={i.item_code}>
                    {i.item_code} · {i.description}
                  </option>
                ))}
              </select>
              {chosen ? (
                <p className="text-xs text-muted-foreground">
                  In stock: <b>{chosen.stock_quantity.toLocaleString()}</b> at {chosen.warehouse}. Suppliers will see it as &quot;{chosen.description}&quot;.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">Choose an item you already stock, or describe a new one below.</p>
              )}
            </div>
            {!chosen && (
              <div className="space-y-2">
                <Label htmlFor="title">New item name</Label>
                <Input id="title" required value={f.title} onChange={set("title")} placeholder="e.g. Hydraulic pump assembly" />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="desc">Specs and notes (optional)</Label>
              <Textarea id="desc" value={f.description} onChange={set("description")} placeholder="Specs, quality, delivery location…" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="qty">Quantity</Label>
                <Input id="qty" type="number" min={1} required value={f.quantity} onChange={set("quantity")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="erp">ERP system</Label>
                <select id="erp" value={f.erp} onChange={set("erp")} className={selectCls}>
                  <option value="sap">SAP</option>
                  <option value="infor">Infor LN</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="tp">Target unit price (optional)</Label>
                <Input id="tp" type="number" min={0} step="0.01" value={f.target_price} onChange={set("target_price")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="nb">Needed by (optional)</Label>
                <Input id="nb" type="date" value={f.needed_by} onChange={set("needed_by")} />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="dl">Quote deadline</Label>
                <div className="flex gap-2">
                  <Input id="dl" type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
                  <Button type="button" variant="outline" onClick={() => setDeadline("")} disabled={!deadline}>
                    No deadline
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  Suppliers can quote until this time. After it, quotes are closed and you can award or extend the deadline. Suppliers who haven&apos;t quoted get a reminder a day before.
                </p>
              </div>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Who can respond?</legend>
              <label className="flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm">
                <input type="radio" name="audience" className="mt-1" checked={audience === "all"} onChange={() => setAudience("all")} />
                <span>
                  <b>Open to all suppliers</b>
                  <span className="block text-xs text-muted-foreground">Every supplier can see and quote it, including suppliers who join later.</span>
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-2 rounded-md border p-3 text-sm">
                <input type="radio" name="audience" className="mt-1" checked={audience === "selected"} onChange={() => setAudience("selected")} />
                <span>
                  <b>Selected suppliers only</b>
                  <span className="block text-xs text-muted-foreground">Only the suppliers you tick below can see it.</span>
                </span>
              </label>
              {audience === "selected" && (
                <div className="space-y-2 pl-1">
                  <div className="flex justify-end">
                    <button type="button" className="text-xs underline" onClick={() => setInvited(invited.length === allIds.length ? [] : allIds)}>
                      {invited.length === allIds.length ? "Clear all" : "Select all"}
                    </button>
                  </div>
                  <div className="grid gap-2 rounded-md border p-3 sm:grid-cols-2">
                    {suppliers.data?.map((s) => (
                      <label key={s.id} className="flex cursor-pointer items-center gap-2 text-sm">
                        <input type="checkbox" checked={invited.includes(s.id)} onChange={() => toggle(s.id)} />
                        {s.supplier_name}
                      </label>
                    ))}
                    {suppliers.data?.length === 0 && <p className="text-sm text-muted-foreground">No suppliers yet.</p>}
                  </div>
                </div>
              )}
            </fieldset>

            <div className="space-y-2">
              <Label htmlFor="files">Attachments (drawings, specs; max 10 MB each)</Label>
              <Input id="files" type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
              {files.length > 0 && (
                <ul className="text-xs text-muted-foreground">
                  {files.map((file) => (
                    <li key={file.name}>
                      {file.name} ({fileSize(file.size)})
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <ErrorNote message={error} />
            <Button type="submit" disabled={busy}>
              {busy ? "Posting…" : "Post requirement"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </>
  );
}
