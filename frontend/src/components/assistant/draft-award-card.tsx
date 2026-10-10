"use client";
// Draft award from draft_award: shows the ranking and the exact ERP call (SRS §6.3 "Show the facts"), sized for the
// chat panel. Nothing is saved until the buyer clicks Confirm, which calls the normal award endpoint (SRS §8 human in the loop).
import { useState } from "react";
import Link from "next/link";
import { api, money } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ErrorAnswer, RankingList, erpName, type Comparison, type RankedResponse } from "./answer-templates";

export interface DraftAward extends Comparison {
  requirement_id: number;
  saved: false;
  proposed: RankedResponse;
  erp_call: { erp: string; operation: string; supplier_name: string; item_code: string | null; quantity: number; unit_price: number; total_price: number };
  confirm: { method: "POST"; path: string; body: { quote_id: number } };
}

type State = { kind: "draft" } | { kind: "saving" } | { kind: "cancelled" } | { kind: "awarded"; poNumber: string; poId: number } | { kind: "error"; message: string };

export function DraftAwardCard({ draft, onNavigate }: { draft: DraftAward; onNavigate?: () => void }) {
  const [state, setState] = useState<State>({ kind: "draft" });
  const call = draft.erp_call;
  const erp = erpName(call.erp);

  async function confirm() {
    setState({ kind: "saving" });
    try {
      const r = await api<{ po_number: string; po_id: number }>(draft.confirm.path, { body: draft.confirm.body });
      setState({ kind: "awarded", poNumber: r.po_number, poId: r.po_id });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : "Award failed" });
    }
  }

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="font-medium">
        Draft award · {draft.req_number} · <span className="font-normal text-muted-foreground">{state.kind === "awarded" ? "saved" : "not saved"}</span>
      </div>
      <RankingList ranking={draft.ranking} highlight={draft.proposed.quote_id} />
      <div className="rounded-md bg-muted/50 px-3 py-2">
        <div className="text-xs text-muted-foreground">ERP call on confirm</div>
        <div>
          {erp} · {call.operation}
        </div>
        <div className="text-xs">
          {call.supplier_name} · {call.item_code ?? "—"} · {call.quantity} × {money(call.unit_price)} = {money(call.total_price)}
        </div>
      </div>
      {state.kind === "awarded" ? (
        <p>
          ✓ Awarded to {draft.proposed.supplier_name}. {state.poNumber} created in {erp}.{" "}
          <Link href={`/purchase-orders/${state.poId}`} onClick={onNavigate} className="font-medium underline">
            Open PO ›
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
            <Button size="sm" onClick={confirm} disabled={state.kind === "saving"}>
              {state.kind === "saving" ? "Awarding…" : "Confirm award"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
