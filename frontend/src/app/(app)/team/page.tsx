"use client";
import { useState } from "react";
import { Copy, KeyRound } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import type { TeamInspector } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

function randomPassword(): string {
  const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint32Array(12));
  return Array.from(bytes, (b) => chars[b % chars.length]).join("");
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied");
  } catch {
    toast.error("Copy is blocked here. Select the text and press Ctrl+C.");
  }
}

/** A buyer's own inspectors: they see and inspect this buyer's shipments only. */
export default function TeamPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useFetch<TeamInspector[]>(user?.role === "buyer" ? "/api/team" : null);
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [created, setCreated] = useState<{ name: string; email: string; password: string } | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<TeamInspector | null>(null);
  const [edit, setEdit] = useState({ name: "", password: "" });

  if (user?.role !== "buyer") return <ErrorNote message="Buyers manage their own inspectors here." />;

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      await api("/api/team", { body: form });
      setCreated(form);
      setForm({ name: "", email: "", password: "" });
      await reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not create the inspector");
    } finally {
      setBusy(false);
    }
  }

  async function patch(u: TeamInspector, body: object, ok: string) {
    setBusy(true);
    try {
      await api(`/api/team/${u.id}`, { method: "PATCH", body });
      toast.success(ok);
      setEditing(null);
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="My inspectors" description="Inspectors you add receive and inspect your shipments only. They sign in like anyone else; give them the email and password." />

      {created && (
        <Card className="mb-6 border-amber-500/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4" />
              {created.name} can now sign in
            </CardTitle>
            <CardDescription>Share these details with them. The password is not shown again.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="w-20 text-muted-foreground">Email</span>
              <span className="font-mono">{created.email}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-20 text-muted-foreground">Password</span>
              <span className="font-mono">{created.password}</span>
            </div>
            <div className="flex gap-2 pt-1">
              <Button size="sm" variant="outline" onClick={() => copy(`Email: ${created.email}\nPassword: ${created.password}`)}>
                <Copy className="mr-1 size-4" />
                Copy both
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setCreated(null)}>
                Done
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="mb-6 max-w-2xl">
        <CardHeader>
          <CardTitle>Add an inspector</CardTitle>
          <CardDescription>They will be told about shipments for your orders and can scan, test and decide on them. They cannot see other buyers&apos; goods.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="in-name">Name</Label>
              <Input id="in-name" required maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Priya, receiving dock" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="in-email">Email (their login)</Label>
              <Input id="in-email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="inspector@yourcompany.com" />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="in-pass">Password (at least 8 characters)</Label>
              <div className="flex gap-2">
                <Input id="in-pass" required minLength={8} maxLength={128} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="font-mono" />
                <Button type="button" variant="outline" onClick={() => setForm({ ...form, password: randomPassword() })}>
                  Generate
                </Button>
              </div>
            </div>
            <div className="sm:col-span-2">
              <ErrorNote message={formError} />
              <Button type="submit" disabled={busy}>
                Add inspector
              </Button>
            </div>
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
              <TableHead>Status</TableHead>
              <TableHead className="hidden md:table-cell">Shipments decided</TableHead>
              <TableHead className="hidden md:table-cell">Last sign-in</TableHead>
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
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  You have no inspectors yet. Until you add one, company inspectors (if any) handle your shipments.
                </TableCell>
              </TableRow>
            )}
            {data?.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.name}</TableCell>
                <TableCell className="hidden sm:table-cell">{u.email}</TableCell>
                <TableCell>
                  {u.active ? (
                    <Badge variant="outline" className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400">Active</Badge>
                  ) : (
                    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">Disabled</Badge>
                  )}
                </TableCell>
                <TableCell className="hidden md:table-cell">{u.inspected}</TableCell>
                <TableCell className="hidden md:table-cell">{u.last_login ? dateTime(u.last_login) : "Never"}</TableCell>
                <TableCell className="space-x-2 text-right">
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => { setEditing(u); setEdit({ name: u.name, password: "" }); }}>
                    Edit
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => patch(u, { active: !u.active }, u.active ? `${u.name} disabled` : `${u.name} enabled`)}>
                    {u.active ? "Disable" : "Enable"}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Edit {editing?.name}</DialogTitle>
            <DialogDescription>Rename the inspector or set a new password for them.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="ed-name">Name</Label>
              <Input id="ed-name" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ed-pass">New password (leave empty to keep it)</Label>
              <div className="flex gap-2">
                <Input id="ed-pass" value={edit.password} minLength={8} onChange={(e) => setEdit({ ...edit, password: e.target.value })} className="font-mono" />
                <Button type="button" variant="outline" onClick={() => setEdit({ ...edit, password: randomPassword() })}>
                  Generate
                </Button>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button
              disabled={busy || !edit.name.trim() || (edit.password !== "" && edit.password.length < 8)}
              onClick={async () => {
                if (!editing) return;
                await patch(editing, { name: edit.name, ...(edit.password ? { password: edit.password } : {}) }, "Saved");
                if (edit.password) setCreated({ name: edit.name, email: editing.email, password: edit.password });
              }}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
