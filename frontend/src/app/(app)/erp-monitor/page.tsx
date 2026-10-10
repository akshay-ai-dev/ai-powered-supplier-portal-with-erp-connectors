"use client";
import { useState } from "react";
import { RefreshCw, Search, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

const ERPS = {
  sap: {
    label: "SAP (demo)",
    views: [
      ["Purchase orders", "/api/erp-monitor/sap/purchase-orders"],
      ["Inbound deliveries", "/api/erp-monitor/sap/inbound-deliveries"],
      ["Stock movements", "/api/erp-monitor/sap/stock-movements"],
      ["Invoice blocks", "/api/erp-monitor/sap/invoice-blocks"],
      ["Materials", "/api/erp-monitor/sap/materials"],
    ],
  },
  infor: {
    label: "Infor LN (demo)",
    views: [
      ["Orders", "/api/erp-monitor/infor/orders"],
      ["Receipts", "/api/erp-monitor/infor/receipts"],
      ["Stock movements", "/api/erp-monitor/infor/stock-movements"],
      ["Invoice holds", "/api/erp-monitor/infor/invoice-holds"],
      ["Items", "/api/erp-monitor/infor/items"],
    ],
  },
  "sap-live": {
    label: "SAP live",
    views: [
      ["Purchase orders", "/api/erp-monitor/live/sap/purchase-orders"],
      ["Suppliers", "/api/erp-monitor/live/sap/suppliers"],
      ["Requisitions", "/api/erp-monitor/live/sap/requisitions"],
      ["Goods receipts", "/api/erp-monitor/live/sap/goods-receipts"],
      ["Supplier invoices", "/api/erp-monitor/live/sap/supplier-invoices"],
      ["Materials", "/api/erp-monitor/live/sap/materials"],
    ],
  },
} as const;

// SAP live: what the search box looks up on each tab (the record's own number).
const SEARCH_BY: Record<string, string> = {
  "Purchase orders": "PO number",
  Suppliers: "supplier no",
  Requisitions: "requisition number",
  "Goods receipts": "material document number",
  "Supplier invoices": "invoice number",
  Materials: "product ID",
};

// SAP's own field name -> label shown
const LIVE_LABELS: Record<string, string> = {
  Supplier: "Supplier No",
};

const cell = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v ?? ""));

export default function ErpMonitorPage() {
  const { user } = useAuth();
  const [erp, setErp] = useState<keyof typeof ERPS>("sap");
  const [view, setView] = useState(0);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const live = erp === "sap-live";
  const viewLabel = ERPS[erp].views[view][0];
  const path = ERPS[erp].views[view][1] + (live && search ? `?q=${encodeURIComponent(search)}` : "");
  const pick = (k: keyof typeof ERPS, i: number) => {
    setErp(k);
    setView(i);
    setDraft("");
    setSearch("");
  };
  // Only buyers and admins use the ERP Monitor; the backend feed enforces the same rule.
  const allowed = user?.role === "buyer" || user?.role === "admin";
  const { data, error, loading, reload } = useFetch<Record<string, unknown>[]>(allowed ? path : null);

  if (user && !allowed) return <ErrorNote message="The ERP Monitor is only available to buyers and admins." />;
  const columns = data && data.length ? Object.keys(data[0]) : [];

  return (
    <>
      <PageHeader title="ERP monitor" description="Live view of what the mock ERPs hold: POs pushed, inbound deliveries, stock movements and invoice holds.">
        <Button variant="outline" size="sm" onClick={() => reload()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh
        </Button>
      </PageHeader>
      <div className="mb-4 flex flex-wrap gap-2">
        {(Object.keys(ERPS) as (keyof typeof ERPS)[]).map((k) => (
          <button
            key={k}
            onClick={() => pick(k, 0)}
            className={`rounded-md border px-4 py-1.5 text-sm ${erp === k ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50"}`}
          >
            {ERPS[k].label}
          </button>
        ))}
        <span className="mx-2 hidden border-l sm:block" />
        {ERPS[erp].views.map(([label], i) => (
          <button key={label} onClick={() => pick(erp, i)} className={`rounded-full border px-3 py-1 text-sm ${view === i ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50"}`}>
            {label}
          </button>
        ))}
      </div>
      {live && (
        <>
          <p className="mb-3 text-sm text-muted-foreground">Read-only data straight from SAP S/4HANA (SAP&apos;s sandbox demo data). The first 20 records are shown.</p>
          <form
            className="mb-3 flex max-w-md gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(draft.trim());
            }}
          >
            <Input aria-label={`Search by ${SEARCH_BY[viewLabel]}`} placeholder={`Search by ${SEARCH_BY[viewLabel]}`} value={draft} maxLength={20} onChange={(e) => setDraft(e.target.value)} />
            <Button type="submit" variant="outline" size="sm" className="h-9">
              <Search className="mr-1 size-4" />
              Search
            </Button>
            {search && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-9"
                onClick={() => {
                  setDraft("");
                  setSearch("");
                }}
              >
                <X className="mr-1 size-4" />
                Clear
              </Button>
            )}
          </form>
        </>
      )}
      <ErrorNote message={error} />
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead key={c} className="font-mono text-xs">
                  {live ? (LIVE_LABELS[c] ?? c) : c}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell className="text-center text-muted-foreground">Loading…</TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={Math.max(columns.length, 1)} className="text-center text-muted-foreground">
                  Nothing here yet.
                </TableCell>
              </TableRow>
            )}
            {data?.map((row, i) => (
              <TableRow key={i}>
                {columns.map((c) => (
                  <TableCell key={c} className="max-w-xs truncate font-mono text-xs" title={cell(row[c])}>
                    {cell(row[c])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}

