"use client";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorNote, PageHeader } from "@/components/page-header";

interface SyncResult {
  erp: string;
  items_added: number;
  items_updated: number;
  suppliers_added: number;
}

export default function AdminDataPage() {
  const { user } = useAuth();
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  if (user?.role !== "admin") return <ErrorNote message="Administrators only." />;

  async function sync(erp: "sap" | "infor") {
    setBusy(erp);
    try {
      const r = await api<SyncResult>(`/api/erp/sync/${erp}`, { method: "POST", body: {} });
      toast.success(`${erp.toUpperCase()}: ${r.items_added} items added, ${r.items_updated} updated, ${r.suppliers_added} suppliers added`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setBusy(null);
    }
  }

  async function reset() {
    setBusy("reset");
    try {
      await api("/api/admin/reset", { body: { confirm } });
      setConfirm("");
      toast.success("Data reset. Demo data restored, mock ERPs reset, emails cleared.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader title="Data & ERP" description="Synchronise master data and reset the environment." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Sync from ERP</CardTitle>
            <CardDescription>Pulls items, stock and suppliers. The ERP is the source of truth for item stock.</CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button disabled={busy !== null} onClick={() => sync("sap")}>
              {busy === "sap" ? "Syncing…" : "Sync SAP"}
            </Button>
            <Button variant="outline" disabled={busy !== null} onClick={() => sync("infor")}>
              {busy === "infor" ? "Syncing…" : "Sync Infor LN"}
            </Button>
          </CardContent>
        </Card>
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Reset data</CardTitle>
            <CardDescription>
              Deletes all requirements, quotes, purchase orders, notifications, audit logs, emails and every user except you, then restores the demo data.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input aria-label="Type RESET to confirm" placeholder="Type RESET to confirm" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <Button variant="destructive" disabled={confirm !== "RESET" || busy !== null} onClick={reset}>
              {busy === "reset" ? "Resetting…" : "Reset all data"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
