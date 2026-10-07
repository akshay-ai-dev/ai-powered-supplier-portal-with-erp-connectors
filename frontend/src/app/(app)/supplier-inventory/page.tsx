"use client";
// Supplier's read-only inventory list. Kept separate from the buyer's Inventory page (/inventory) so changes
// there never affect suppliers; it reuses the same table layout and stock badges.
import { useEffect, useState } from "react";
import { shortDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { InventoryItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

function Stock({ qty }: { qty: number }) {
  if (qty === 0) return <Badge variant="destructive">Out of stock</Badge>;
  if (qty < 20) return <Badge variant="outline" className="border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400">Low · {qty}</Badge>;
  return <span>{qty.toLocaleString()}</span>;
}

export default function SupplierInventoryPage() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, error, loading } = useFetch<InventoryItem[]>(`/api/inventory?q=${encodeURIComponent(debounced)}`);

  if (user && user.role !== "supplier") return <ErrorNote message="This page is for suppliers. Buyers use Inventory in their own menu." />;

  return (
    <>
      <PageHeader title="Inventory" description="Stock availability across warehouses.">
        <Input className="w-64" placeholder="Search item code or description…" value={q} onChange={(e) => setQ(e.target.value)} />
      </PageHeader>

      <ErrorNote message={error} />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Item code</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Stock</TableHead>
              <TableHead className="hidden sm:table-cell">Warehouse</TableHead>
              <TableHead className="hidden md:table-cell">ERP</TableHead>
              <TableHead className="hidden md:table-cell">Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  No items match.
                </TableCell>
              </TableRow>
            )}
            {data?.map((i) => (
              <TableRow key={i.id}>
                <TableCell className="font-mono text-xs">{i.item_code}</TableCell>
                <TableCell>{i.description}</TableCell>
                <TableCell>
                  <Stock qty={i.stock_quantity} />
                </TableCell>
                <TableCell className="hidden sm:table-cell">{i.warehouse}</TableCell>
                <TableCell className="hidden uppercase md:table-cell">{i.source}</TableCell>
                <TableCell className="hidden md:table-cell">{shortDate(i.updated_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
