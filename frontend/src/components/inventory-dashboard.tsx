"use client";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useFetch } from "@/lib/use-fetch";
import type { InventoryItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote } from "@/components/page-header";

// Same look as the tiles on the Dashboard page.
function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold">{value}</div>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

// Same badges as the Inventory page.
function Stock({ qty }: { qty: number }) {
  if (qty === 0) return <Badge variant="destructive">Out of stock</Badge>;
  if (qty < 20) return <Badge variant="outline" className="border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400">Low · {qty}</Badge>;
  return <span>{qty.toLocaleString()}</span>;
}

/**
 * Inventory section of the supplier Dashboard, built from the inventory table.
 * `stats` are the caller's own tiles; they share the first row with the inventory tiles.
 */
export function InventoryDashboard({ stats }: { stats?: React.ReactNode }) {
  const { data, error, loading } = useFetch<InventoryItem[]>("/api/inventory");

  if (loading || !data) {
    return (
      <>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {stats}
          {loading && <Skeleton className="h-28" />}
        </div>
        {!loading && <ErrorNote message={error ?? "No inventory data"} />}
      </>
    );
  }

  const warehouses = [...new Set(data.map((i) => i.warehouse))].sort();
  const byWarehouse = warehouses.map((warehouse) => ({ warehouse, count: data.filter((i) => i.warehouse === warehouse).length }));
  const reorder = [...data].sort((a, b) => a.stock_quantity - b.stock_quantity).slice(0, 3);

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stats}
        <Stat label="Inventory items" value={data.length} />
      </div>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Items by warehouse</CardTitle>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={byWarehouse}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
              <XAxis dataKey="warehouse" tickLine={false} axisLine={false} fontSize={12} />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} width={28} />
              <Tooltip cursor={{ fill: "var(--accent)" }} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8 }} />
              <Bar dataKey="count" name="Items" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Needs manufacturing</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Description</TableHead>
                <TableHead>Item code</TableHead>
                <TableHead>Stock</TableHead>
                <TableHead>Warehouse</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {reorder.length === 0 && (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-muted-foreground">
                    No inventory items.
                  </TableCell>
                </TableRow>
              )}
              {reorder.map((i) => (
                <TableRow key={i.id}>
                  <TableCell>{i.description}</TableCell>
                  <TableCell>{i.item_code}</TableCell>
                  <TableCell>
                    <Stock qty={i.stock_quantity} />
                  </TableCell>
                  <TableCell>{i.warehouse}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
