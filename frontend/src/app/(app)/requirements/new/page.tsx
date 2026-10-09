"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FileSearch } from "lucide-react";
import { toast } from "sonner";
import { api, fileSize, localInputToIso, toLocalInput, uploadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { FieldIssue, InventoryItem, Requirement, RequirementDraft, RequirementDraftItem, Supplier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ErrorNote, PageHeader } from "@/components/page-header";

const selectCls = "h-9 w-full rounded-md border bg-background px-3 text-sm";

// Plain-language reasons for the "Missing or uncertain fields" section; falls back to the model's own message.
const ISSUE_TEXT: Record<string, string> = {
  not_found: "not found in the document — add it if you have it.",
  multiple_items: "the document lists several items — pick the one this requirement is for.",
  relative_date: "only a relative term was given (e.g. “within 4 weeks”), not an actual date — set the date yourself.",
  ambiguous_date: "the date is numerically ambiguous — confirm the day and month.",
  ambiguous_value: "a value looked like this field but was unclear, so it was left out.",
  historical_date: "the date is in the past — set a current date.",
  only_total_amount: "only a total amount was shown, not a unit price — enter the target unit price.",
  time_zone_unclear: "the document gives a time but no clear time zone — confirm the deadline time.",
};
const FIELD_LABEL: Record<string, string> = {
  title: "Item name",
  description: "Specs and notes",
  quantity: "Quantity",
  target_price: "Target unit price",
  needed_by: "Needed by",
  quote_deadline: "Quote deadline",
};

// The draft quote deadline carries the document's local wall-clock (optionally with a resolved zone
// offset we do not re-interpret here). Read the literal date/time into the datetime-local field so it
// shows exactly as printed — never via new Date(), which would re-zone it and could cross a day.
function draftDeadlineToInput(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (!m) return "";
  return `${m[1]}-${m[2]}-${m[3]}T${m[4] ?? "00"}:${m[5] ?? "00"}`;
}

// True when an extracted deadline string carries an explicit UTC offset (…-06:00 / …+00:00 / …Z).
function deadlineHasOffset(iso: string | null): boolean {
  return !!iso && /\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)$/.test(iso);
}

// The UTC instant to POST as quote_deadline. When the extracted deadline carries an explicit offset
// AND the buyer has not changed the shown value, keep that exact instant (preserve the document's
// moment regardless of the buyer's own time zone). Otherwise — the buyer edited the value, it was
// naive (unclear zone), or it was typed by hand — interpret the shown wall-clock in the buyer's own
// time zone, which is the existing localInputToIso rule.
function resolveDeadlineForSubmit(input: string, draftIso: string | null, draftInput: string | null): string | null {
  if (!input) return null;
  const edited = draftInput === null || input !== draftInput;
  if (!edited && deadlineHasOffset(draftIso)) return new Date(draftIso as string).toISOString();
  return localInputToIso(input);
}

// Keep only one distinct-named item per name (a document may repeat a line); used to decide whether
// the buyer must choose between several items.
function distinctItems(items: RequirementDraftItem[]): RequirementDraftItem[] {
  const seen = new Set<string>();
  const out: RequirementDraftItem[] = [];
  for (const it of items ?? []) {
    const name = (it.item_name ?? "").trim();
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(it);
  }
  return out;
}

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

  // --- Document pre-fill (saves nothing; only fills the editable draft) ---
  const [draft, setDraft] = useState<RequirementDraft | null>(null);
  const [draftItems, setDraftItems] = useState<RequirementDraftItem[]>([]); // >= 2 distinct items: buyer must choose
  const [chosenItem, setChosenItem] = useState<number | null>(null);
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [evidence, setEvidence] = useState<RequirementDraft["evidence"]>([]);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const [extractFile, setExtractFile] = useState<File | null>(null);
  const [docUrl, setDocUrl] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  // Quote-deadline submit handling: the raw extracted deadline (may carry an explicit offset), the
  // datetime-local value we pre-filled (to detect whether the buyer edited it), whether the extracted
  // zone was unclear, and the buyer's confirmation for an unclear-zone deadline.
  const [draftDeadlineIso, setDraftDeadlineIso] = useState<string | null>(null);
  const [draftDeadlineInput, setDraftDeadlineInput] = useState<string | null>(null);
  const [deadlineZoneUnclear, setDeadlineZoneUnclear] = useState(false);
  const [deadlineConfirmed, setDeadlineConfirmed] = useState(false);

  // Let the buyer open the uploaded document while reviewing. The file is not uploaded anywhere on submit.
  useEffect(() => {
    if (!extractFile) {
      setDocUrl(null);
      return;
    }
    const url = URL.createObjectURL(extractFile);
    setDocUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [extractFile]);

  if (user && user.role !== "buyer" && user.role !== "admin") return <ErrorNote message="Only buyers can post requirements." />;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const chosen = inventory.data?.find((i) => i.item_code === f.item_code);
  const title = chosen ? chosen.description : f.title.trim(); // one source of truth: the inventory item, or the new item's name
  const allIds = suppliers.data?.map((s) => s.id) ?? [];
  const toggle = (id: number) => setInvited(invited.includes(id) ? invited.filter((x) => x !== id) : [...invited, id]);

  const multi = draftItems.length >= 2;
  const evidenceFor = (field: string) => evidence.filter((e) => e.field === field);

  // Quote-deadline submit rule. The buyer "edited" the deadline when the shown value differs from what
  // we pre-filled (or there was no pre-fill). An unedited extracted deadline with an explicit offset is
  // posted as that exact instant; an unedited deadline whose zone was unclear must be confirmed first.
  const localTz = (typeof Intl !== "undefined" && Intl.DateTimeFormat().resolvedOptions().timeZone) || "your local time zone";
  const deadlineEdited = draftDeadlineInput === null || deadline !== draftDeadlineInput;
  const deadlinePreservesOffset = !!deadline && !deadlineEdited && deadlineHasOffset(draftDeadlineIso);
  const deadlineZoneUnclearShown = !!deadline && !deadlineEdited && deadlineZoneUnclear;
  const deadlineNeedsConfirm = deadlineZoneUnclearShown && !deadlineConfirmed;
  const deadlineOffsetLabel = draftDeadlineIso?.match(/([+-]\d{2}:\d{2})$/)?.[1] ?? "its offset";

  // Fill the editable fields from a draft. Document-level fields (specs, dates) fill either way; the
  // item-specific fields (name, quantity, target price) fill only when there is a single item — when a
  // document lists several, the buyer picks one first and quantities are never combined.
  function applyDraft(d: RequirementDraft) {
    setDraft(d);
    setIssues(d.field_issues ?? []);
    setEvidence(d.evidence ?? []);
    const items = distinctItems(d.items ?? []);
    setChosenItem(null);
    if (items.length >= 2) {
      setDraftItems(items);
      setF((p) => ({ ...p, item_code: "", description: d.description ?? p.description, needed_by: d.needed_by ?? p.needed_by }));
    } else {
      setDraftItems([]);
      setF((p) => ({
        ...p,
        item_code: "", // an extracted item is described by name, not an existing inventory code
        title: d.title ?? p.title,
        description: d.description ?? p.description,
        quantity: d.quantity != null ? String(d.quantity) : p.quantity,
        target_price: d.target_price != null ? String(d.target_price) : p.target_price,
        needed_by: d.needed_by ?? p.needed_by,
      }));
    }
    if (d.quote_deadline) {
      const input = draftDeadlineToInput(d.quote_deadline);
      setDeadline(input);
      setDraftDeadlineIso(d.quote_deadline);
      setDraftDeadlineInput(input);
    } else {
      setDraftDeadlineIso(null);
      setDraftDeadlineInput(null);
    }
    setDeadlineZoneUnclear((d.field_issues ?? []).some((i) => i.field === "quote_deadline" && i.code === "time_zone_unclear"));
    setDeadlineConfirmed(false);
  }

  function chooseItem(i: number) {
    const it = draftItems[i];
    if (!it) return;
    setChosenItem(i);
    setF((p) => ({
      ...p,
      item_code: "",
      title: it.item_name ?? "",
      description: it.specs ?? p.description,
      quantity: it.quantity != null ? String(it.quantity) : "",
      target_price: it.target_price != null ? String(it.target_price) : "",
    }));
  }

  async function extractDoc(doc: File) {
    setError(null);
    setExtracting(true);
    try {
      const d = await uploadFile<RequirementDraft>("/api/extraction-prefill/requirements", doc);
      applyDraft(d);
      setExtractFile(doc);
      toast.success("Draft extracted. Review every field before posting — nothing has been saved yet.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not read the document.");
    } finally {
      setExtracting(false);
    }
  }

  // Unique issues to surface (no duplicates), limited to fields the buyer can act on here.
  const seen = new Set<string>();
  const reviewReasons = issues.filter((it) => {
    if (!(it.field in FIELD_LABEL)) return false;
    const k = `${it.field}:${it.code}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  // A label row with a small Evidence toggle (only once a draft exists), plus the expandable box.
  const labelRow = (field: string, text: string, htmlFor?: string) => (
    <div className="flex items-center justify-between">
      <Label htmlFor={htmlFor}>{text}</Label>
      {draft && (
        <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground underline" onClick={() => setOpenEvidence(openEvidence === field ? null : field)}>
          <FileSearch className="size-3" /> Evidence
        </button>
      )}
    </div>
  );
  const evidenceBox = (field: string) => {
    if (openEvidence !== field) return null;
    const ev = evidenceFor(field);
    return (
      <div className="rounded-md border bg-muted/40 p-2 text-xs">
        {ev.length > 0 ? (
          <ul className="space-y-1">
            {ev.map((e, i) => (
              <li key={i}>
                {e.page != null ? <b>Page {e.page}: </b> : <b>Source text: </b>}
                <span className="italic">“{e.text}”</span>
              </li>
            ))}
            <li className="text-muted-foreground">As reported by the extractor; the exact position is not highlighted — please confirm against the document.</li>
          </ul>
        ) : (
          <span className="text-muted-foreground">Source location unavailable.</span>
        )}
      </div>
    );
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (multi && chosenItem === null) return setError("The document lists several items. Choose which one this requirement is for.");
    if (!title) return setError("Describe the item you need.");
    const quantity = Number(f.quantity);
    if (!Number.isInteger(quantity) || quantity <= 0) return setError("Enter the quantity as a whole number greater than zero.");
    if (deadlineNeedsConfirm) return setError("The document showed a deadline time but no clear time zone. Confirm the deadline below before posting.");
    const quoteDeadline = resolveDeadlineForSubmit(deadline, draftDeadlineIso, draftDeadlineInput);
    if (quoteDeadline && new Date(quoteDeadline).getTime() <= Date.now()) return setError("The quote deadline must be in the future.");
    if (audience === "selected" && invited.length === 0) return setError("Select at least one supplier, or choose Open to all suppliers.");
    setBusy(true);
    let created: Requirement;
    try {
      created = await api<Requirement>("/api/requirements", {
        body: {
          title,
          description: f.description,
          item_code: f.item_code || null,
          quantity,
          target_price: f.target_price ? Number(f.target_price) : null,
          needed_by: f.needed_by || null,
          erp: f.erp,
          quote_deadline: quoteDeadline,
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
      <div className="max-w-2xl">
      </div>
      <Card className="max-w-2xl">
        <CardContent className="pt-6">
          <form onSubmit={submit} className="space-y-4">
            {/* Pre-fill from a document. Upload returns an editable draft only — it saves nothing and attaches nothing. */}
            <fieldset className="space-y-2 rounded-md border p-3">
              <legend className="px-1 text-sm font-medium">Upload PDF or image (optional)</legend>
              <Label htmlFor="extract">Purchase request, requisition or RFQ brief (max 10 MB)</Label>
              <Input
                id="extract"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,application/pdf,image/*"
                disabled={extracting}
                onChange={(e) => {
                  const doc = e.target.files?.[0];
                  e.target.value = "";
                  if (doc) extractDoc(doc);
                }}
              />
              <p className="text-xs text-muted-foreground" role="status">
                {extracting
                  ? "Reading the document…"
                  : extractFile
                    ? `Read “${extractFile.name}”. Suggestions below are editable; nothing is saved until you post. This file is not attached — add it under Attachments if you want it kept.`
                    : "Optional. We suggest the item name, specs, quantity, target unit price, needed-by date and quote deadline for you to review. The ERP system stays your choice."}
              </p>
              {extractFile && docUrl && (
                <a href={docUrl} target="_blank" rel="noreferrer" className="inline-block text-xs underline">
                  View uploaded document
                </a>
              )}
            </fieldset>

            {/* Several items in the document: choose one. Quantities are never combined. */}
            {multi && (
              <fieldset className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                <legend className="px-1 text-sm font-medium">This document lists several items — choose one</legend>
                <p className="text-xs text-muted-foreground">A requirement is for one item. Pick which one this is for; the item fields below fill from your choice and quantities are never added together.</p>
                <div className="space-y-2">
                  {draftItems.map((it, i) => (
                    <label key={i} className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm ${chosenItem === i ? "border-primary bg-primary/5" : ""}`}>
                      <input type="radio" name="draft-item" className="mt-1" checked={chosenItem === i} onChange={() => chooseItem(i)} />
                      <span>
                        <b>{it.item_name}</b>
                        {it.quantity != null && <span className="text-xs text-muted-foreground"> · qty {it.quantity}{it.unit_of_measure ? ` ${it.unit_of_measure}` : ""}</span>}
                        {it.target_price != null && <span className="text-xs text-muted-foreground"> · target {it.target_price}/unit</span>}
                        {it.specs && <span className="block text-xs text-muted-foreground">{it.specs}</span>}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

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
                {labelRow("title", "New item name", "title")}
                <Input id="title" required value={f.title} onChange={set("title")} placeholder="e.g. Hydraulic pump assembly" />
                {evidenceBox("title")}
              </div>
            )}
            <div className="space-y-2">
              {labelRow("description", "Specs and notes (optional)", "desc")}
              <Textarea id="desc" value={f.description} onChange={set("description")} placeholder="Specs, quality, delivery location…" />
              {evidenceBox("description")}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                {labelRow("quantity", "Quantity", "qty")}
                <Input id="qty" type="number" min={1} step={1} required value={f.quantity} onChange={set("quantity")} />
                {evidenceBox("quantity")}
              </div>
              <div className="space-y-2">
                <Label htmlFor="erp">ERP system</Label>
                <select id="erp" value={f.erp} onChange={set("erp")} className={selectCls}>
                  <option value="sap">SAP</option>
                  <option value="infor">Infor LN</option>
                </select>
              </div>
              <div className="space-y-2">
                {labelRow("target_price", "Target unit price (optional)", "tp")}
                <Input id="tp" type="number" min={0} step="0.01" value={f.target_price} onChange={set("target_price")} />
                {evidenceBox("target_price")}
              </div>
              <div className="space-y-2">
                {labelRow("needed_by", "Needed by (optional)", "nb")}
                <Input id="nb" type="date" value={f.needed_by} onChange={set("needed_by")} />
                {evidenceBox("needed_by")}
              </div>
              <div className="space-y-2 sm:col-span-2">
                {labelRow("quote_deadline", "Quote deadline", "dl")}
                <div className="flex gap-2">
                  <Input id="dl" type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
                  <Button type="button" variant="outline" onClick={() => setDeadline("")} disabled={!deadline}>
                    No deadline
                  </Button>
                </div>
                {evidenceBox("quote_deadline")}
                {deadlinePreservesOffset && (
                  <p className="text-xs text-muted-foreground">
                    Time taken from the document ({deadlineOffsetLabel}). Posting keeps this exact moment; edit it to use your own time zone ({localTz}).
                  </p>
                )}
                {deadlineZoneUnclearShown && (
                  <label className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs">
                    <input type="checkbox" className="mt-0.5" checked={deadlineConfirmed} onChange={(e) => setDeadlineConfirmed(e.target.checked)} />
                    <span>The document showed a deadline time but no clear time zone. Confirm this time is correct — it will be saved in your time zone ({localTz}).</span>
                  </label>
                )}
                {deadline && deadlineEdited && draftDeadlineInput !== null && (
                  <p className="text-xs text-muted-foreground">Edited deadline — saved in your time zone ({localTz}).</p>
                )}
                <p className="text-xs text-muted-foreground">
                  Suppliers can quote until this time. After it, quotes are closed and you can award or extend the deadline. Suppliers who haven&apos;t quoted get a reminder a day before.
                </p>
              </div>
            </div>

            {/* Missing or uncertain fields — immediately above "Who can respond?". */}
            {reviewReasons.length > 0 && (
              <fieldset className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                <legend className="px-1 text-sm font-medium">Missing or uncertain fields</legend>
                <p className="text-xs text-muted-foreground">From the document you uploaded. Check or fill these before posting.</p>
                <ul className="space-y-1 text-xs">
                  {reviewReasons.map((it, i) => (
                    <li key={i}>
                      <span className="font-medium">{FIELD_LABEL[it.field] ?? it.field}:</span> {ISSUE_TEXT[it.code] ?? it.message}
                    </li>
                  ))}
                </ul>
              </fieldset>
            )}

            <fieldset className="space-y-2 rounded-md">
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
