"use client";
// Confirm card for the draft tools (draft_request, draft_po_approval, draft_quote, draft_arrival,
// draft_delivery_approval, and create_purchase_order in the chat): shows what would be saved and the exact call.
// Nothing is saved until the user clicks the confirm button, which calls the normal REST endpoint (SRS §6.1).
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ChatDraft, ChatReply } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ErrorAnswer } from "./answer-templates";

type Saved = { id: number; req_number?: string; po_number?: string; shipment_no?: string };
type Done = { kind: "cancelled" } | { kind: "saved"; link: { href: string; label: string } };
type State = { kind: "draft" } | { kind: "saving" } | Done | { kind: "error"; message: string };

/** Give a draft answer an id when it arrives, so its card can remember whether it was confirmed or cancelled. */
export function stampDraft(reply: ChatReply): ChatReply {
  const r = reply.result;
  if (r && typeof r === "object" && "confirm" in r && !("draft_id" in r)) {
    const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    return { ...reply, result: { ...r, draft_id: id } };
  }
  return reply;
}

/** A draft card's outcome, kept for the browser session: leaving the page and coming back must not offer Confirm
 *  again for a draft that was already saved (that would save it twice). */
export function useDraftOutcome<T>(draftId: string | undefined): [T | null, (outcome: T) => void] {
  const key = draftId ? `erp_draft_outcome_${draftId}` : null;
  const [outcome, setOutcome] = useState<T | null>(() => {
    if (!key) return null;
    try {
      const raw = sessionStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : null;
    } catch {
      return null;
    }
  });
  const remember = (o: T) => {
    setOutcome(o);
    if (!key) return;
    try {
      sessionStorage.setItem(key, JSON.stringify(o));
    } catch {
      /* storage unavailable: the card just forgets after a reload */
    }
  };
  return [outcome, remember];
}

/** Where the saved record lives in the app, from the endpoint that saved it. */
function linkFor(path: string, r: Saved): { href: string; label: string } {
  if (path.startsWith("/api/shipments")) return { href: `/shipments/${r.id}`, label: `Open ${r.shipment_no ?? "shipment"} ›` };
  if (path.startsWith("/api/purchase-orders")) return { href: `/purchase-orders/${r.id}`, label: `Open ${r.po_number ?? "order"} ›` };
  return { href: `/requirements/${r.id}`, label: `Open ${r.req_number ?? "request"} ›` };
}

export function ConfirmCard({ tool, draft, onNavigate }: { tool: string; draft: ChatDraft & { draft_id?: string }; onNavigate?: () => void }) {
  const [done, setDone] = useDraftOutcome<Done>(draft.draft_id);
  const [pending, setPending] = useState<State>({ kind: "draft" });
  const state: State = done ?? pending;
  const { method, path, body, label } = draft.confirm;

  async function confirm() {
    setPending({ kind: "saving" });
    try {
      const r = await api<Saved>(path, { method, body });
      setDone({ kind: "saved", link: linkFor(path, r) });
    } catch (e) {
      setPending({ kind: "error", message: e instanceof Error ? e.message : "Saving failed" });
    }
  }

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="font-medium">
        Draft · <span className="font-normal text-muted-foreground">{state.kind === "saved" ? "saved" : "not saved"}</span>
      </div>
      <div className="space-y-0.5">
        {Object.entries(draft.summary).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <span className="shrink-0 text-muted-foreground">{k}</span>
            <span className="text-right font-medium">{String(v)}</span>
          </div>
        ))}
      </div>
      <div className="rounded-md bg-muted/50 px-3 py-1.5 font-mono text-xs text-muted-foreground">
        On confirm: {method} {path}
      </div>
      {state.kind === "saved" ? (
        <p>
          ✓ Saved.{" "}
          <Link href={state.link.href} onClick={onNavigate} className="font-medium underline">
            {state.link.label}
          </Link>
        </p>
      ) : state.kind === "cancelled" ? (
        <p className="text-muted-foreground">Cancelled. Nothing was saved.</p>
      ) : (
        <>
          {state.kind === "error" && <ErrorAnswer message={state.message} />}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setDone({ kind: "cancelled" })} disabled={state.kind === "saving"}>
              Cancel
            </Button>
            <Button size="sm" onClick={confirm} disabled={state.kind === "saving"} data-tool={tool}>
              {state.kind === "saving" ? "Saving…" : label}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
