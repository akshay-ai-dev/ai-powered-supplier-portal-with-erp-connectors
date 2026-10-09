"use client";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { Supplier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote, PageHeader } from "@/components/page-header";

export default function ProfilePage() {
  const { user } = useAuth();
  const { data, error, loading } = useFetch<Supplier>(user?.supplier_id ? `/api/suppliers/${user.supplier_id}` : null);
  const [form, setForm] = useState({ supplier_name: "", email: "", phone: "", address: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (data) setForm({ supplier_name: data.supplier_name, email: data.email, phone: data.phone, address: data.address });
  }, [data]);

  if (!user?.supplier_id) return <ErrorNote message="Profiles are managed for supplier accounts only." />;
  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error) return <ErrorNote message={error} />;

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`/api/suppliers/${user!.supplier_id}`, { method: "PUT", body: form });
      toast.success("Profile updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Supplier profile" description="Buyers see these details when raising orders." />
      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Company details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={save} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="n">Company name</Label>
              <Input id="n" required value={form.supplier_name} onChange={set("supplier_name")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="e">Order email</Label>
              <Input id="e" type="email" required value={form.email} readOnly />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p">Phone</Label>
              <Input
                id="p"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                maxLength={25}
                placeholder="+1 555 010 1234"
                value={form.phone}
                readOnly
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="a">Address</Label>
              <Input id="a" value={form.address} onChange={set("address")} />
            </div>
            <Button type="submit" disabled={busy}>
              Save changes
            </Button>
          </form>
        </CardContent>
      </Card>
    </>
  );
}
