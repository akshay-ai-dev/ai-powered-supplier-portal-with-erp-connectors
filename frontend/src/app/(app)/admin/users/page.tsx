"use client";
import { useState } from "react";
import { toast } from "sonner";
import { api, shortDate } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

interface AdminUser {
  id: number;
  name: string;
  email: string;
  role: string;
  active: number;
  created_at: string;
}

export default function AdminUsersPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useFetch<AdminUser[]>(user?.role === "admin" ? "/api/admin/users" : null);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "buyer" });
  const [busy, setBusy] = useState(false);

  if (user?.role !== "admin") return <ErrorNote message="Administrators only." />;
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Users" description="Create accounts, disable access and reset passwords." />
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Add user</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                await api("/api/admin/users", { body: form });
                setForm({ name: "", email: "", password: "", role: "buyer" });
              }, "User created");
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="un">Name</Label>
              <Input id="un" required value={form.name} onChange={set("name")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ue">Email</Label>
              <Input id="ue" type="email" required value={form.email} onChange={set("email")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="up">Password</Label>
              <Input id="up" type="password" minLength={8} required value={form.password} onChange={set("password")} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ur">Role</Label>
              <select id="ur" value={form.role} onChange={set("role")} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
                <option value="buyer">Buyer</option>
                <option value="supplier">Supplier</option>
                <option value="inspector">Warehouse inspector</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <Button type="submit" disabled={busy}>
              Create
            </Button>
          </form>
        </CardContent>
      </Card>

      <ErrorNote message={error} />
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead className="hidden sm:table-cell">Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="hidden md:table-cell">Created</TableHead>
              <TableHead />
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
            {data?.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.name}</TableCell>
                <TableCell className="hidden sm:table-cell">{u.email}</TableCell>
                <TableCell className="capitalize">{u.role}</TableCell>
                <TableCell>
                  {u.active ? (
                    <Badge variant="outline" className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400">
                      Active
                    </Badge>
                  ) : (
                    <Badge variant="destructive">Disabled</Badge>
                  )}
                </TableCell>
                <TableCell className="hidden md:table-cell">{shortDate(u.created_at)}</TableCell>
                <TableCell className="space-x-2 text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => {
                      const password = window.prompt(`New password for ${u.email} (min 8 characters):`);
                      if (password) run(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { password } }), "Password updated");
                    }}
                  >
                    Reset password
                  </Button>
                  {u.id !== user.id && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => run(() => api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { active: !u.active } }), u.active ? "User disabled" : "User enabled")}
                    >
                      {u.active ? "Disable" : "Enable"}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
