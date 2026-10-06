"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ErrorNote } from "@/components/page-header";
import { ThemeToggle } from "@/components/theme-toggle";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { signIn, signUp } = useAuth();
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "buyer" as "buyer" | "supplier" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState(""); // a scanned QR code arrives as /login?next=/units/CODE; keep it when switching between sign in and register
  useEffect(() => setNext(new URLSearchParams(window.location.search).get("next") ?? ""), []);
  const keepNext = next ? `?next=${encodeURIComponent(next)}` : "";
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await signIn(form.email, form.password);
      else await signUp(form.name, form.email, form.password, form.role);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <main className="relative grid min-h-screen place-items-center p-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{mode === "login" ? "Sign in" : "Create account"}</CardTitle>
          <CardDescription>ERP Copilot: procurement and supplier portal</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input id="name" required value={form.name} onChange={set("name")} />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" required value={form.email} onChange={set("email")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" required minLength={mode === "register" ? 8 : 1} value={form.password} onChange={set("password")} />
            </div>
            {mode === "register" && (
              <div className="space-y-2">
                <Label htmlFor="role">I am a</Label>
                <select id="role" value={form.role} onChange={set("role")} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
                  <option value="buyer">Buyer</option>
                  <option value="supplier">Supplier</option>
                </select>
              </div>
            )}
            <ErrorNote message={error} />
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Register"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            {mode === "login" ? (
              <>
                No account?{" "}
                <Link className="underline" href={`/register${keepNext}`}>
                  Register
                </Link>
              </>
            ) : (
              <>
                Have an account?{" "}
                <Link className="underline" href={`/login${keepNext}`}>
                  Sign in
                </Link>
              </>
            )}
          </p>
          {mode === "login" && (
            <div className="mt-4 rounded-md bg-muted p-3 text-xs text-muted-foreground">
              Demo: <b>buyer@demo.com</b>, <b>supplier@demo.com</b> or <b>admin@demo.com</b> / Password123!
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

