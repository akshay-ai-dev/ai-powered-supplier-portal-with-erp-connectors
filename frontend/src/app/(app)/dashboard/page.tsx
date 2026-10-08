"use client";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { dateTime, money } from "@/lib/api";
import type { AdminDashboard, BuyerDashboard, InspectorDashboard, SupplierDashboard } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { AgentBadge } from "@/components/agent-badge";
import { InventoryDashboard } from "@/components/inventory-dashboard";

function Stat({ label, value, hint, href }: { label: string; value: number | string; hint?: string; href?: string }) {
  const body = (
    <Card className={href ? "transition-colors hover:bg-accent/40" : ""}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold">{value}</div>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { data, error, loading } = useFetch<BuyerDashboard | SupplierDashboard | AdminDashboard | InspectorDashboard>("/api/dashboard");

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }
  if (error || !data) return <ErrorNote message={error ?? "No data"} />;

  if (data.role === "inspector") {
    return (
      <>
        <PageHeader title={`Welcome, ${user?.name}`} description="Goods receiving and inspection." />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Incoming" value={data.incoming} hint="Shipped, not yet arrived" href="/shipments" />
          <Stat label="Awaiting inspection" value={data.awaiting_inspection} hint="Arrived, no decision yet" href="/shipments" />
          <Stat label="Approved" value={data.approved} href="/shipments" />
          <Stat label="Rejected" value={data.rejected} href="/shipments" />
        </div>
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Notifications</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.notifications.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet.</p>}
            {data.notifications.map((n) => (
              <div key={n.id} className="border-b pb-3 last:border-0 last:pb-0">
                <div className="text-sm font-medium">{n.title}</div>
                <div className="text-sm text-muted-foreground">{n.message}</div>
                <div className="mt-1 text-xs text-muted-foreground">{dateTime(n.created_at)}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </>
    );
  }

  if (data.role === "admin") {
    const count = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
    return (
      <>
        <PageHeader title="Administration" description="System-wide overview." />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Users" value={count(data.users_by_role)} hint={Object.entries(data.users_by_role).map(([r, n]) => `${n} ${r}`).join(" · ")} href="/admin/users" />
          <Stat label="Requirements" value={count(data.requirements_by_status)} hint={Object.entries(data.requirements_by_status).map(([s, n]) => `${n} ${s.toLowerCase()}`).join(" · ")} href="/requirements" />
          <Stat label="Purchase orders" value={count(data.orders_by_status)} hint={Object.entries(data.orders_by_status).map(([s, n]) => `${n} ${s.toLowerCase()}`).join(" · ")} />
          <Stat label="Suppliers / items" value={`${data.suppliers} / ${data.inventory_items}`} href="/admin/data" />
        </div>
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Recent activity</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.recent_audit.length === 0 && <p className="text-sm text-muted-foreground">No activity yet.</p>}
            {data.recent_audit.map((a, i) => (
              <div key={i} className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span>
                  <b>{a.entity}</b> {a.entity_id} · {a.action}
                  {a.detail && <span className="text-muted-foreground"> ({a.detail})</span>}
                  {a.user_name && <span className="text-muted-foreground"> by {a.user_name}</span>}{" "}
                  <AgentBadge channel={a.channel} compact />
                </span>
                <span className="text-xs text-muted-foreground">{dateTime(a.created_at)}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </>
    );
  }

  if (data.role === "supplier") {
    return (
      <>
        <PageHeader title={`Welcome, ${user?.name}`} description="Your orders and deliveries at a glance." />
        <InventoryDashboard
          stats={
            <>
              <Stat label="Active orders" value={data.active_orders} />
              <Stat label="Pending deliveries" value={data.pending_deliveries} />
            </>
          }
        />
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Notifications</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {data.notifications.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet.</p>}
            {data.notifications.map((n) => (
              <div key={n.id} className="border-b pb-3 last:border-0 last:pb-0">
                <div className="text-sm font-medium">{n.title}</div>
                <div className="text-sm text-muted-foreground">{n.message}</div>
                <div className="mt-1 text-xs text-muted-foreground">{dateTime(n.created_at)}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </>
    );
  }

  const statusData = Object.entries(data.orders_by_status).map(([status, count]) => ({ status, count }));
  return (
    <>
      <PageHeader title="Dashboard" description="Procurement overview." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Open orders" value={data.open_orders} hint="Draft, pending or approved" />
        <Stat label="Inventory items" value={data.inventory_count} hint={`${data.low_stock_count} low on stock`} href="/inventory" />
        <Stat label="Suppliers" value={data.supplier_count} href="/suppliers" />
        <Stat label="Low stock" value={data.low_stock_count} hint="Fewer than 20 units" href="/inventory" />
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Orders by status</CardTitle>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis dataKey="status" tickLine={false} axisLine={false} fontSize={12} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} width={28} />
                <Tooltip cursor={{ fill: "var(--accent)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8 }} />
                <Bar dataKey="count" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Spend by supplier</CardTitle>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.spend_by_supplier} layout="vertical" margin={{ left: 16 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border)" />
                <XAxis type="number" tickLine={false} axisLine={false} fontSize={12} tickFormatter={(v) => `$${v}`} />
                <YAxis type="category" dataKey="name" tickLine={false} axisLine={false} fontSize={12} width={110} />
                <Tooltip formatter={(v) => money(Number(v))} cursor={{ fill: "var(--accent)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8 }} />
                <Bar dataKey="total" fill="var(--chart-2)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Recent activity</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.recent_activity.length === 0 && <p className="text-sm text-muted-foreground">No activity yet.</p>}
          {data.recent_activity.map((a, i) => (
            <div key={i} className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
              <span>
                <b>{a.entity_id}</b> · {a.action}
                {a.detail && <span className="text-muted-foreground"> ({a.detail})</span>}
                {a.user_name && <span className="text-muted-foreground"> by {a.user_name}</span>}
              </span>
              <span className="text-xs text-muted-foreground">{dateTime(a.created_at)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </>
  );
}
