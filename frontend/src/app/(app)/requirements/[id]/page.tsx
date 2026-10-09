"use client";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ArrowLeft, Download, MessageSquare, Paperclip, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, deadlineLabel, downloadFile, fileSize, localInputToIso, money, shortDate, uploadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AiBanner, useAiFill } from "@/lib/prefill";
import { useFetch } from "@/lib/use-fetch";
import type { Requirement, Supplier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { AgentBadge } from "@/components/agent-badge";
import { HistoryCard } from "@/components/history-card";
import { MessageThread } from "@/components/message-thread";

export default function RequirementDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user } = useAuth();
  const { data: r, error, loading, reload } = useFetch<Requirement>(`/api/requirements/${id}`);
  const [busy, setBusy] = useState(false);
  const suppliers = useFetch<Supplier[]>(user?.role === "supplier" ? null : "/api/suppliers");
  const [inviteId, setInviteId] = useState("");
  const [chatWith, setChatWith] = useState<number | null>(null);
  const [newDeadline, setNewDeadline] = useState("");
  const [quote, setQuote] = useState({ unit_price: "", lead_time_days: "7", message: "" });

  useEffect(() => {
    if (r?.my_quote && r.my_quote.status !== "Withdrawn")
      setQuote({ unit_price: String(r.my_quote.unit_price), lead_time_days: String(r.my_quote.lead_time_days), message: r.my_quote.message });
  }, [r]);

  // declared after the effect above so the assistant's values win over the saved quote
  const ai = useAiFill(
    "submit_quote",
    (v) =>
      setQuote((q) => ({
        unit_price: v.unit_price != null ? String(v.unit_price) : q.unit_price,
        lead_time_days: v.lead_time_days != null ? String(v.lead_time_days) : q.lead_time_days,
        message: v.message ?? q.message,
      })),
    id,
    !!r,
  );

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error || !r) return <ErrorNote message={error ?? "Not found"} />;
  const isSupplier = user?.role === "supplier";
  const canWrite = user?.role === "buyer" || user?.role === "admin";
  const isBuyer = user?.role === "buyer";
  const open = r.status === "Open";

  return (
    <>
      <Link href="/requirements" className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="mr-1 size-4" />
        All requirements
      </Link>
      <PageHeader title={r.title} description={
        <>
          {r.req_number} · posted {shortDate(r.created_at)}
          {r.buyer_name && <span className="mt-1 block">{r.buyer_name}</span>}
        </>
      }>
        <AgentBadge channel={r.created_via} />
        <StatusBadge status={r.stage} />
        {canWrite && open && (
          <Button variant="outline" disabled={busy} onClick={() => run(() => api(`/api/requirements/${id}/cancel`, { method: "POST" }), "Requirement cancelled")}>
            Cancel requirement
          </Button>
        )}
      </PageHeader>

      <Card className="mb-6">
        <CardContent className="grid gap-4 pt-6 text-sm sm:grid-cols-4">
          <div><div className="text-muted-foreground">Quantity</div>{r.quantity}{r.item_code && <span className="ml-1 font-mono text-xs">({r.item_code})</span>}</div>
          <div><div className="text-muted-foreground">Target price</div>{r.target_price != null ? money(r.target_price) : "—"}</div>
          <div><div className="text-muted-foreground">Needed by</div>{r.needed_by ? shortDate(r.needed_by) : "—"}</div>
          <div className="sm:col-span-2">
            <div className="text-muted-foreground">Quote deadline</div>
            {r.quote_deadline ? (
              <span className={r.quotes_closed ? "text-orange-700 dark:text-orange-400" : ""}>
                {new Date(r.quote_deadline).toLocaleString()} · <b>{r.quotes_closed ? "quotes closed" : deadlineLabel(r.quote_deadline)}</b>
              </span>
            ) : (
              "None"
            )}
            {isBuyer && open && (
              <div className="mt-2 flex flex-wrap gap-2">
                <Input aria-label="New quote deadline" type="datetime-local" className="w-56" value={newDeadline} onChange={(e) => setNewDeadline(e.target.value)} />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !newDeadline}
                  onClick={() => run(async () => { await api(`/api/requirements/${id}/deadline`, { method: "PUT", body: { quote_deadline: localInputToIso(newDeadline) } }); setNewDeadline(""); }, "Deadline updated. Suppliers have been told.")}
                >
                  {r.quotes_closed ? "Extend and reopen" : "Change deadline"}
                </Button>
                {r.quote_deadline && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => api(`/api/requirements/${id}/deadline`, { method: "PUT", body: { quote_deadline: null } }), "Deadline removed")}>
                    Remove deadline
                  </Button>
                )}
              </div>
            )}
          </div>
          <div>
            <div className="text-muted-foreground">Purchase order</div>
            {r.po_id ? <Link className="underline" href={`/purchase-orders/${r.po_id}`}>{r.po_number}</Link> : "—"}
          </div>
          <div><div className="text-muted-foreground">ERP</div><span className="uppercase">{r.erp}</span></div>
          <div><div className="text-muted-foreground">Ship date</div>{r.ship_date || "—"}</div>
          <div><div className="text-muted-foreground">Carrier</div>{r.carrier || "—"}</div>
          <div><div className="text-muted-foreground">Tracking numbers</div><span className="whitespace-pre-wrap break-all">{r.tracking_number || "—"}</span></div>
          <div className="sm:col-span-2"><div className="text-muted-foreground">Lot numbers</div><p className="whitespace-pre-wrap break-words">{r.lot_numbers || "—"}</p></div>
          <div className="sm:col-span-2"><div className="text-muted-foreground">Serial numbers</div><p className="whitespace-pre-wrap break-words">{r.serial_numbers || "—"}</p></div>
          {r.description && <p className="whitespace-pre-wrap sm:col-span-4">{r.description}</p>}
        </CardContent>
      </Card>

      {!isSupplier && (
        <Card>
          <CardHeader>
            <CardTitle>Supplier quotes ({r.quotes?.length ?? 0})</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Supplier</TableHead>
                  <TableHead className="text-right">Unit price</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead className="hidden sm:table-cell">Lead time</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {r.quotes?.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground">
                      No quotes yet.
                    </TableCell>
                  </TableRow>
                )}
                {r.quotes?.map((q) => (
                  <TableRow key={q.id}>
                    <TableCell>
                      <div className="font-medium">{q.supplier_name}</div>
                      {q.message && <div className="text-xs text-muted-foreground">{q.message}</div>}
                    </TableCell>
                    <TableCell className="text-right">{money(q.unit_price)}</TableCell>
                    <TableCell className="text-right">{money(q.unit_price * r.quantity)}</TableCell>
                    <TableCell className="hidden sm:table-cell">{q.lead_time_days} days</TableCell>
                    <TableCell>
                      <StatusBadge status={q.status} />
                    </TableCell>
                    <TableCell className="text-right">
                      {canWrite && open && q.status === "Submitted" && (
                        <Button size="sm" disabled={busy} onClick={() => run(() => api(`/api/requirements/${id}/award`, { body: { quote_id: q.id } }), "Awarded. Purchase order created.")}>
                          Award
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {(isBuyer || isSupplier) && (
      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="size-4" />
            Messages
            {isSupplier && r.unread_messages > 0 && <span className="rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">{r.unread_messages} new</span>}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {isSupplier ? (
            <MessageThread requirementId={r.id} onActivity={reload} />
          ) : (
            (() => {
              // every supplier the buyer can talk to: invited, already quoted, or already wrote in
              const people = new Map<number, { name: string; unread: number }>();
              r.invites?.forEach((i) => people.set(i.supplier_id, { name: i.supplier_name, unread: 0 }));
              r.quotes?.forEach((q) => people.set(q.supplier_id, { name: q.supplier_name ?? `Supplier ${q.supplier_id}`, unread: 0 }));
              r.threads?.forEach((t) => people.set(t.supplier_id, { name: t.supplier_name, unread: t.unread }));
              const list = [...people.entries()];
              if (list.length === 0) return <p className="text-sm text-muted-foreground">No supplier has responded yet. Suppliers can message you once they open the requirement.</p>;
              const active = chatWith ?? list[0][0];
              return (
                <>
                  <div className="flex flex-wrap gap-2">
                    {list.map(([sid, p]) => (
                      <button
                        key={sid}
                        onClick={() => setChatWith(sid)}
                        className={`rounded-full border px-3 py-1 text-sm ${sid === active ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50"}`}
                      >
                        {p.name}
                        {p.unread > 0 && <span className="ml-2 rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{p.unread}</span>}
                      </button>
                    ))}
                  </div>
                  <MessageThread key={active} requirementId={r.id} supplierId={active} onActivity={reload} />
                </>
              );
            })()
          )}
        </CardContent>
      </Card>
      )}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Paperclip className="size-4" />
            Attachments ({r.attachments?.length ?? 0})
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {r.attachments?.length === 0 && <p className="text-sm text-muted-foreground">No files attached.</p>}
          {r.attachments?.map((a) => (
            <div key={a.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">
                {a.filename} <span className="text-xs text-muted-foreground">({fileSize(a.size)})</span>
              </span>
              <span className="flex shrink-0 gap-1">
                <Button variant="ghost" size="icon" aria-label={`Download ${a.filename}`} onClick={() => downloadFile(`/api/attachments/${a.id}/download`, a.filename).catch((e) => toast.error(e.message))}>
                  <Download className="size-4" />
                </Button>
                {canWrite && open && (
                  <Button variant="ghost" size="icon" aria-label={`Remove ${a.filename}`} disabled={busy} onClick={() => run(() => api(`/api/attachments/${a.id}`, { method: "DELETE" }), "File removed")}>
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </span>
            </div>
          ))}
          {isBuyer && open && (
            <div>
              <Label htmlFor="upload" className="mb-1 block text-xs text-muted-foreground">
                Add a file (PDF, image, DWG/DXF/STEP, Office, CSV, ZIP; max 10 MB)
              </Label>
              <Input
                id="upload"
                type="file"
                disabled={busy}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) run(() => uploadFile(`/api/requirements/${id}/attachments`, f), `${f.name} uploaded`);
                }}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {!isSupplier && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>{r.open_to_all ? "Audience" : `Invited suppliers (${r.invites?.length ?? 0})`}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {r.open_to_all ? <p className="text-sm">Open to <b>all suppliers</b>, including ones who join later. Suppliers who decline are listed below.</p> : null}
            <ul className="flex flex-wrap gap-2">
              {r.invites?.map((i) => (
                <li key={i.supplier_id} className="rounded-full border px-3 py-1 text-sm">
                  {i.supplier_name}
                  <span className="ml-2 text-xs text-muted-foreground">{i.declined ? `declined${i.decline_reason ? `: ${i.decline_reason}` : ""}` : i.quoted ? "quoted" : "no response"}</span>
                </li>
              ))}
            </ul>
            {canWrite && open && !r.open_to_all && (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => run(() => api(`/api/requirements/${id}/open-to-all`, { method: "POST" }), "Now open to all suppliers")}>
                Open to all suppliers
              </Button>
            )}
            {canWrite && open && !r.open_to_all && (
              <div className="flex gap-2">
                <select aria-label="Invite supplier" value={inviteId} onChange={(e) => setInviteId(e.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
                  <option value="">Invite another supplier…</option>
                  {suppliers.data
                    ?.filter((s) => !r.invites?.some((i) => i.supplier_id === s.id))
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.supplier_name}
                      </option>
                    ))}
                </select>
                <Button
                  variant="outline"
                  disabled={busy || !inviteId}
                  onClick={() => run(async () => { await api(`/api/requirements/${id}/invite`, { body: { supplier_ids: [Number(inviteId)] } }); setInviteId(""); }, "Supplier invited")}
                >
                  Invite
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!isSupplier && <HistoryCard history={r.history} />}

      {isSupplier && ai.any && (
        <div className="max-w-xl">
          <AiBanner show onDismiss={ai.clear} />
        </div>
      )}
      {isSupplier && (
        <Card className="max-w-xl">
          <CardHeader>
            <CardTitle>{r.my_quote && r.my_quote.status !== "Withdrawn" ? "Your quote" : "Apply with a quote"}</CardTitle>
          </CardHeader>
          <CardContent>
            {r.my_quote && r.my_quote.status !== "Submitted" && r.my_quote.status !== "Withdrawn" && (
              <p className="mb-4 text-sm">
                Status: <StatusBadge status={r.my_quote.status} />
                {r.awarded_to_me && r.po_id && (
                  <> · <Link className="underline" href={`/purchase-orders/${r.po_id}`}>Open PO {r.po_number} to update delivery</Link></>
                )}
              </p>
            )}
            {open && !r.quotes_closed ? (
              <form
                className="space-y-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  run(
                    () => api(`/api/requirements/${id}/quote`, { method: "PUT", body: { unit_price: Number(quote.unit_price), lead_time_days: Number(quote.lead_time_days), message: quote.message } }),
                    "Quote submitted",
                  );
                }}
              >
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="up">Unit price</Label>
                    <Input id="up" type="number" min={0} step="0.01" required value={quote.unit_price} onChange={(e) => setQuote({ ...quote, unit_price: e.target.value })} className={ai.ring("unit_price")} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="lt">Lead time (days)</Label>
                    <Input id="lt" type="number" min={0} required value={quote.lead_time_days} onChange={(e) => setQuote({ ...quote, lead_time_days: e.target.value })} className={ai.ring("lead_time_days")} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="msg">Message to buyer</Label>
                  <Textarea id="msg" value={quote.message} onChange={(e) => setQuote({ ...quote, message: e.target.value })} className={ai.ring("message")} />
                </div>
                <div className="flex gap-2">
                  <Button type="submit" disabled={busy}>
                    {r.my_quote && r.my_quote.status === "Submitted" ? "Update quote" : "Submit quote"}
                  </Button>
                  {r.my_quote && r.my_quote.status === "Submitted" && (
                    <Button type="button" variant="outline" disabled={busy} onClick={() => run(() => api(`/api/requirements/${id}/quote`, { method: "DELETE" }), "Quote withdrawn")}>
                      Withdraw
                    </Button>
                  )}
                </div>
              </form>
            ) : (
              <p className="text-sm text-muted-foreground">{open ? "The quote deadline has passed. The buyer may extend it, so keep an eye on your notifications." : "This requirement is closed for quotes."}</p>
            )}
          </CardContent>
        </Card>
      )}
    </>
  );
}
