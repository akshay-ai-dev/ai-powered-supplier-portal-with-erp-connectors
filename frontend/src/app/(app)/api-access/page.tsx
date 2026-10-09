"use client";
import { useState } from "react";
import { Copy, KeyRound } from "lucide-react";
import { toast } from "sonner";
import { api, apiBase, dateTime } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorNote, PageHeader } from "@/components/page-header";

interface Token {
  id: number;
  name: string;
  prefix: string;
  scope: "read" | "write";
  status: "active" | "expired" | "revoked";
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  owner_name?: string;
  owner_email?: string;
}
interface Created extends Token {
  token: string;
}

function StatusPill({ status }: { status: Token["status"] }) {
  if (status === "active") return <Badge variant="outline" className="border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400">Active</Badge>;
  return <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground capitalize">{status}</Badge>;
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied");
  } catch {
    toast.error("Copy is blocked on non-HTTPS pages. Select the text and press Ctrl+C.");
  }
}

function TokenTable({ tokens, showOwner, onRevoke, busy }: { tokens: Token[]; showOwner?: boolean; onRevoke: (t: Token) => void; busy: boolean }) {
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            {showOwner && <TableHead className="hidden sm:table-cell">Owner</TableHead>}
            <TableHead>Scope</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="hidden md:table-cell">Last used</TableHead>
            <TableHead className="hidden md:table-cell">Expires</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {tokens.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} className="text-center text-muted-foreground">
                No tokens yet.
              </TableCell>
            </TableRow>
          )}
          {tokens.map((t) => (
            <TableRow key={t.id}>
              <TableCell>
                <div className="font-medium">{t.name}</div>
                <div className="font-mono text-xs text-muted-foreground">{t.prefix}…</div>
              </TableCell>
              {showOwner && <TableCell className="hidden sm:table-cell">{t.owner_name}<div className="text-xs text-muted-foreground">{t.owner_email}</div></TableCell>}
              <TableCell>{t.scope === "write" ? "Read + drafts" : "Read only"}</TableCell>
              <TableCell><StatusPill status={t.status} /></TableCell>
              <TableCell className="hidden md:table-cell">{t.last_used_at ? dateTime(t.last_used_at) : "Never"}</TableCell>
              <TableCell className="hidden md:table-cell">{t.expires_at ? dateTime(t.expires_at) : "Never"}</TableCell>
              <TableCell className="text-right">
                {t.status === "active" && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => onRevoke(t)}>
                    Revoke
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function ApiAccessPage() {
  const { user } = useAuth();
  const allowed = user?.role === "buyer" || user?.role === "admin";
  const mine = useFetch<Token[]>(allowed ? "/api/tokens" : null);
  const everyone = useFetch<Token[]>(user?.role === "admin" ? "/api/admin/tokens" : null);
  const [form, setForm] = useState({ name: "", scope: "read", days: "90" });
  const [created, setCreated] = useState<Created | null>(null);
  const [client, setClient] = useState<"desktop" | "code" | "other">("desktop");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!allowed) return <ErrorNote message="API tokens are available to buyers and administrators." />;

  const mcpUrl = `${apiBase()}/mcp/`;
  const adminAtLimit = user?.role === "admin" && !!mine.data?.some((t) => t.status === "active");

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setCreated(await api<Created>("/api/tokens", { body: { name: form.name, scope: form.scope, expires_in_days: form.days === "never" ? null : Number(form.days) } }));
      setForm({ ...form, name: "" });
      await Promise.all([mine.reload(), everyone.reload()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create token");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(t: Token) {
    if (!window.confirm(`Revoke "${t.name}"? Anything using it stops working immediately.`)) return;
    setBusy(true);
    try {
      await api(`/api/tokens/${t.id}`, { method: "DELETE" });
      toast.success("Token revoked");
      await Promise.all([mine.reload(), everyone.reload()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Revoke failed");
    } finally {
      setBusy(false);
    }
  }

  const snippets = created
    ? {
        desktop: {
          label: "Claude Desktop",
          hint: "Open Settings → Developer → Edit Config and merge this into the file. Then fully quit Claude Desktop (tray icon → Quit) and reopen it. Needs Node.js installed.",
          text: JSON.stringify(
            {
              mcpServers: {
                erp: {
                  command: "npx",
                  args: ["-y", "mcp-remote", mcpUrl, "--header", "Authorization:${AUTH_HEADER}"],
                  env: { AUTH_HEADER: `Bearer ${created.token}` },
                },
              },
            },
            null,
            2,
          ),
        },
        code: {
          label: "Claude Code",
          hint: "Run this in a terminal.",
          text: `claude mcp add --transport http erp ${mcpUrl} --header "Authorization: Bearer ${created.token}"`,
        },
        other: {
          label: ".mcp.json (other clients)",
          hint: "For Claude Code project files and MCP clients that connect to a URL directly. Do not paste this into Claude Desktop: its config file rejects this format.",
          text: JSON.stringify({ mcpServers: { erp: { type: "http", url: mcpUrl, headers: { Authorization: `Bearer ${created.token}` } } } }, null, 2),
        },
      }
    : null;
  const active = snippets ? snippets[client] : null;

  return (
    <>
      <PageHeader title="API access" description="Let an AI agent work on your behalf. A token acts as you: it sees only your data, and everything it does is audited and flagged as an AI action." />

      {created && (
        <Card className="mb-6 border-amber-500/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4" />
              Copy your token now: {created.name}
            </CardTitle>
            <CardDescription>It is shown only once and cannot be recovered. If you lose it, revoke it and create a new one.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex gap-2">
              <Input readOnly aria-label="New token" value={created.token} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
              <Button variant="outline" onClick={() => copy(created.token)}>
                <Copy className="mr-1 size-4" />
                Copy
              </Button>
            </div>
            {snippets && active && (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2" role="tablist" aria-label="Which app will use this token?">
                  {(Object.keys(snippets) as (keyof typeof snippets)[]).map((k) => (
                    <button
                      key={k}
                      type="button"
                      role="tab"
                      aria-selected={client === k}
                      onClick={() => setClient(k)}
                      className={`rounded-full border px-3 py-1 text-sm ${client === k ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50"}`}
                    >
                      {snippets[k].label}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">{active.hint}</p>
                <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs" onClick={() => copy(active.text)} title="Click to copy">
                  {active.text}
                </pre>
                <Button variant="outline" size="sm" onClick={() => copy(active.text)}>
                  <Copy className="mr-1 size-4" />
                  Copy {active.label} config
                </Button>
              </div>
            )}
            <Button variant="ghost" size="sm" onClick={() => setCreated(null)}>
              I have saved it
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Create a token</CardTitle>
          <CardDescription>{user?.role === "admin" ? "Administrators can have one active token at a time. Revoke your current token before creating another." : "Use a separate token per device or agent, so you can revoke one without affecting the others."}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
            <div className="space-y-1 lg:col-span-1">
              <Label htmlFor="tn">Name</Label>
              <Input id="tn" required maxLength={80} placeholder="e.g. Claude on my laptop" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ts">Permissions</Label>
              <select id="ts" value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
                <option value="read">Read only (look things up)</option>
                <option value="write">Read + create drafts</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="td">Expires</Label>
              <select id="td" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
                <option value="30">In 30 days</option>
                <option value="90">In 90 days</option>
                <option value="180">In 180 days</option>
                <option value="365">In 1 year</option>
                <option value="never">Never</option>
              </select>
            </div>
            <Button type="submit" disabled={busy || mine.loading || adminAtLimit}>
              Create token
            </Button>
          </form>
          <div className="mt-3">
            <ErrorNote message={error} />
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Agents can read requirements, purchase orders, inventory and suppliers, and (with write permission) create Draft purchase orders. They cannot approve, award, close or change users. MCP address:{" "}
            <span className="font-mono">{mcpUrl}</span>
          </p>
        </CardContent>
      </Card>

      <h2 className="mb-3 text-lg font-semibold">Your tokens</h2>
      <ErrorNote message={mine.error} />
      <TokenTable tokens={mine.data ?? []} onRevoke={revoke} busy={busy} />

      {user?.role === "admin" && (
        <>
          <h2 className="mb-3 mt-8 text-lg font-semibold">All users&apos; tokens</h2>
          <ErrorNote message={everyone.error} />
          <TokenTable tokens={everyone.data ?? []} showOwner onRevoke={revoke} busy={busy} />
        </>
      )}
    </>
  );
}
