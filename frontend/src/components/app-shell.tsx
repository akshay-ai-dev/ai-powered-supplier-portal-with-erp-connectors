"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Boxes, ClipboardList, FileSearch, LayoutDashboard, Mail, Database, KeyRound, LogOut, Menu, PackageCheck, Radar, Truck, Users, UserCog, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

const buyerNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/suppliers", label: "Suppliers", icon: Truck },
  { href: "/requirements", label: "Requirements", icon: FileSearch },
  { href: "/purchase-orders", label: "Purchase Orders", icon: ClipboardList },
  { href: "/inventory", label: "Inventory", icon: Boxes },
  { href: "/shipments", label: "Shipments", icon: PackageCheck },
  { href: "/erp-monitor", label: "ERP Monitor", icon: Radar },
  { href: "/api-access", label: "API access", icon: KeyRound },
  { href: "/emails", label: "Emails", icon: Mail },
];
const adminNav = [
  ...buyerNav,
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/data", label: "Data & ERP", icon: Database },
];
const inspectorNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/shipments", label: "Receiving", icon: PackageCheck },
  { href: "/requirements", label: "Requirements", icon: FileSearch },
  { href: "/purchase-orders", label: "Purchase Orders", icon: ClipboardList },
  { href: "/inventory", label: "Inventory", icon: Boxes },
  { href: "/suppliers", label: "Suppliers", icon: Truck },
  { href: "/erp-monitor", label: "ERP Monitor", icon: Radar },
  { href: "/emails", label: "Emails", icon: Mail },
];
const supplierNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/requirements", label: "Requirements", icon: FileSearch },
  { href: "/purchase-orders", label: "My Orders", icon: ClipboardList },
  { href: "/shipments", label: "Shipments", icon: PackageCheck },
  { href: "/emails", label: "Emails", icon: Mail },
  { href: "/profile", label: "Profile", icon: UserCog },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);
  useEffect(() => setOpen(false), [pathname]);

  if (loading || !user) return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Loading…</div>;

  const nav = user.role === "supplier" ? supplierNav : user.role === "admin" ? adminNav : user.role === "inspector" ? inspectorNav : buyerNav;
  const sidebar = (
    <nav className="flex h-full flex-col gap-1 p-4">
      <div className="mb-6 flex items-center gap-2 px-2 text-lg font-semibold">
        <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">E</span>
        ERP Copilot
      </div>
      {nav.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || (href !== "/dashboard" && !!pathname?.startsWith(href));
        return (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
              active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            }`}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
      <div className="mt-auto rounded-md border p-3 text-xs">
        <div className="truncate font-medium">{user.name}</div>
        <div className="truncate text-muted-foreground">{user.email}</div>
        <div className="mt-1 capitalize text-muted-foreground">{user.role}</div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className="sticky top-0 hidden h-screen border-r bg-card md:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-card">{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-background/80 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Menu" onClick={() => setOpen((o) => !o)}>
            {open ? <X className="size-4" /> : <Menu className="size-4" />}
          </Button>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={signOut}>
              <LogOut className="mr-2 size-4" />
              Sign out
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
