"use client";
// Draft award from draft_award: shows the comparison table and the exact ERP call (SRS §6.3 "Show the facts").
// Nothing is saved until the buyer clicks Confirm, which calls the normal award endpoint (SRS §8 human in the loop).
import { useState } from "react";
import Link from "next/link";
import { api, money } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ErrorAnswer, RankingTable, type Comparison, type RankedResponse } from "./answer-templates";

export interface DraftAward extends Comparison {
  requirement_id: number;
  saved: false;
  proposed: RankedResponse;
  erp_call: { erp: string; operation: string; supplier_name: string; item_code: string | null; quantity: number; unit_price: number; total_price: number };
  confirm: { method: "POST"; path: string; body: { quote_id: number } };
}

type State = { kind: "draft" } | { kind: "saving" } | { kind: "cancelled" } | { kind: "awarded"; poNumber: string; poId: number } | { kind: "error"; message: string };

export function DraftAwardCard({ draft }: { draft: DraftAward }) {
  const [state, setState] = useState<State>({ kind: "draft" });
  const call = draft.erp_call;
  const erp = call.erp === "infor" ? "Infor LN" : call.erp.toUpperCase();

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
    <div className="space-y-3 rounded-md border p-3">
      <div className="text-sm font-medium">
        Draft award · {draft.req_number} · <span className="text-muted-foreground">{state.kind === "awarded" ? "saved" : "not saved"}</span>
      </div>
      <RankingTable ranking={draft.ranking} highlight={draft.proposed.quote_id} />
      <div className="rounded-md bg-muted/40 p-3 text-sm">
        <div className="text-xs text-muted-foreground">ERP call on confirm</div>
        <div>
          {erp} · {call.operation}
        </div>
        <div>
          supplier {call.supplier_name} · item {call.item_code ?? "—"} · qty {call.quantity} · {money(call.unit_price)} each ({money(call.total_price)})
        </div>
      </div>
      {state.kind === "awarded" ? (
        <p className="text-sm">
          ✓ Awarded to {draft.proposed.supplier_name}. {state.poNumber} created in {erp}.{" "}
          <Link href={`/purchase-orders/${state.poId}`} className="font-medium underline">
            View PO →
          </Link>
        </p>
      ) : state.kind === "cancelled" ? (
        <p className="text-sm text-muted-foreground">Cancelled. Nothing was saved.</p>
      ) : (
        <>
          {state.kind === "error" && <ErrorAnswer message={state.message} />}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setState({ kind: "cancelled" })} disabled={state.kind === "saving"}>
              Cancel
            </Button>
            <Button onClick={confirm} disabled={state.kind === "saving"}>
              {state.kind === "saving" ? "Awarding…" : "Confirm award"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
