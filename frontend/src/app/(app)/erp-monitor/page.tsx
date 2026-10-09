"use client";
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

const ERPS = {
  sap: {
    label: "SAP",
    views: [
      ["Purchase orders", "/api/erp-monitor/sap/purchase-orders"],
      ["Inbound deliveries", "/api/erp-monitor/sap/inbound-deliveries"],
      ["Stock movements", "/api/erp-monitor/sap/stock-movements"],
      ["Invoice blocks", "/api/erp-monitor/sap/invoice-blocks"],
      ["Materials", "/api/erp-monitor/sap/materials"],
    ],
  },
  infor: {
    label: "Infor LN",
    views: [
      ["Orders", "/api/erp-monitor/infor/orders"],
      ["Receipts", "/api/erp-monitor/infor/receipts"],
      ["Stock movements", "/api/erp-monitor/infor/stock-movements"],
      ["Invoice holds", "/api/erp-monitor/infor/invoice-holds"],
      ["Items", "/api/erp-monitor/infor/items"],
    ],
  },
} as const;

const cell = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v ?? ""));

export default function ErpMonitorPage() {
  const { user } = useAuth();
  const [erp, setErp] = useState<keyof typeof ERPS>("sap");
  const [view, setView] = useState(0);
  const path = ERPS[erp].views[view][1];
  const { data, error, loading, reload } = useFetch<Record<string, unknown>[]>(user?.role === "buyer" ? path : null);

  if (user && user.role !== "buyer") return <ErrorNote message="ERP Monitor is available to buyers." />;
  const columns = data && data.length ? Object.keys(data[0]) : [];

  return (
    <>
      <PageHeader title="ERP Monitor" description="Live view of what the mock ERPs hold: POs pushed, inbound deliveries, stock movements and invoice holds.">
        <Button variant="outline" size="sm" onClick={() => reload()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh
        </Button>
      </PageHeader>
      <div className="mb-4 flex flex-wrap gap-2">
        {(Object.keys(ERPS) as (keyof typeof ERPS)[]).map((k) => (
          <button
            key={k}
            onClick={() => {
              setErp(k);
              setView(0);
            }}
            className={`rounded-md border px-4 py-1.5 text-sm ${erp === k ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50"}`}
          >
            {ERPS[k].label}
          </button>
        ))}
        <span className="mx-2 hidden border-l sm:block" />
        {ERPS[erp].views.map(([label], i) => (
          <button key={label} onClick={() => setView(i)} className={`rounded-full border px-3 py-1 text-sm ${view === i ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50"}`}>
            {label}
          </button>
        ))}
      </div>
      <ErrorNote message={error} />
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c) => (
                <TableHead key={c} className="font-mono text-xs">
                  {c}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={Math.max(columns.length, 1)} className="text-center text-muted-foreground">Loading…</TableCell>
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
