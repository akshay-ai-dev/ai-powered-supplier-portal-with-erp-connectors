"use client";
import { useEffect, useState } from "react";
import { useFetch } from "@/lib/use-fetch";
import type { Supplier } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

export default function SuppliersPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, error, loading } = useFetch<Supplier[]>(`/api/suppliers?q=${encodeURIComponent(debounced)}`);

  return (
    <>
      <PageHeader title="Suppliers" description="Search the supplier directory.">
        <Input className="w-64" placeholder="Search name, email, address…" value={q} onChange={(e) => setQ(e.target.value)} />
      </PageHeader>
      <ErrorNote message={error} />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead className="hidden sm:table-cell">Phone</TableHead>
              <TableHead className="hidden md:table-cell">Address</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && !data && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
                  No suppliers match.
                </TableCell>
              </TableRow>
            )}
            {data?.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium">{s.supplier_name}</TableCell>
                <TableCell>{s.email}</TableCell>
                <TableCell className="hidden sm:table-cell">{s.phone}</TableCell>
                <TableCell className="hidden md:table-cell">{s.address}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
