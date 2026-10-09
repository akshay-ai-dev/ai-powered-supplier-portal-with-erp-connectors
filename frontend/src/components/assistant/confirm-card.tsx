"use client";
// Confirm card for the draft tools (draft_request, draft_po_approval, draft_quote, draft_arrival,
// draft_delivery_approval, and create_purchase_order in the widget): shows what would be saved and the exact call.
// Nothing is saved until the user clicks the confirm button, which calls the normal REST endpoint (SRS §6.1).
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ChatDraft } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ErrorAnswer } from "./answer-templates";

type Saved = { id: number; req_number?: string; po_number?: string; shipment_no?: string };
type State = { kind: "draft" } | { kind: "saving" } | { kind: "cancelled" } | { kind: "saved"; link: { href: string; label: string } } | { kind: "error"; message: string };

/** Where the saved record lives in the app, from the endpoint that saved it. */
function linkFor(path: string, r: Saved): { href: string; label: string } {
  if (path.startsWith("/api/shipments")) return { href: `/shipments/${r.id}`, label: `Open ${r.shipment_no ?? "shipment"} ›` };
  if (path.startsWith("/api/purchase-orders")) return { href: `/purchase-orders/${r.id}`, label: `Open ${r.po_number ?? "order"} ›` };
  return { href: `/requirements/${r.id}`, label: `Open ${r.req_number ?? "request"} ›` };
}

export function ConfirmCard({ tool, draft, onNavigate }: { tool: string; draft: ChatDraft; onNavigate?: () => void }) {
  const [state, setState] = useState<State>({ kind: "draft" });
  const { method, path, body, label } = draft.confirm;

  async function confirm() {
    setState({ kind: "saving" });
    try {
      const r = await api<Saved>(path, { method, body });
      setState({ kind: "saved", link: linkFor(path, r) });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : "Saving failed" });
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
            <Button size="sm" variant="outline" onClick={() => setState({ kind: "cancelled" })} disabled={state.kind === "saving"}>
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
