"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Boxes, ClipboardList, FileSearch, LayoutDashboard, Mail, Database, KeyRound, LogOut, Menu, PackageCheck, Radar, Sparkles, Truck, Users, UserCog, X } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { roleLabel } from "@/lib/roles";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useUnreadEmails } from "@/lib/use-unread-emails";
import { NotificationBell } from "@/components/notification-bell";
import { ChatWidget } from "@/components/chat-widget";

const baseNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/assistant", label: "Buyer Assistant", icon: Sparkles },
  { href: "/suppliers", label: "Suppliers", icon: Truck },
  { href: "/requirements", label: "Requirements", icon: FileSearch },
  { href: "/purchase-orders", label: "Purchase Orders", icon: ClipboardList },
  { href: "/inventory", label: "Inventory", icon: Boxes },
  { href: "/shipments", label: "Shipments", icon: PackageCheck },
  { href: "/erp-monitor", label: "ERP Monitor", icon: Radar },
  { href: "/api-access", label: "API access", icon: KeyRound },
  { href: "/emails", label: "Emails", icon: Mail },
];
// A buyer creates and manages their own inspectors. /units/[code] and the QR label page are reached by link or scan, so they have no entry.
const buyerNav = [...baseNav.slice(0, 7), { href: "/team", label: "My inspectors", icon: UserCog }, ...baseNav.slice(7)];
const adminNav = [
  ...baseNav,
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
  { href: "/emails", label: "Emails", icon: Mail },
];
const supplierNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/inventory", label: "Inventory", icon: Boxes },
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
  const unreadEmails = useUnreadEmails(!!user);
  const leaving = useRef(false); // signing out on purpose: do not remember this page as where to return to

  useEffect(() => {
    if (loading || user) return;
    // A deep link (a scanned QR code opens /units/CODE) goes to the sign-in page and comes back to where it was headed.
    const wanted = pathname + window.location.search;
    router.replace(leaving.current || pathname === "/" || pathname === "/dashboard" ? "/login" : `/login?next=${encodeURIComponent(wanted)}`);
  }, [loading, user, router, pathname]);
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
        const className = `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
          active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
        }`;
        
        if (href === "/emails") {
          const tip =
            unreadEmails === null ? "Emails" : unreadEmails === 0 ? "No unread emails" : `${unreadEmails} unread email${unreadEmails === 1 ? "" : "s"}`;
          return (
            <Tooltip key={href}>
              <TooltipTrigger
                delay={150}
                render={
                  <Link href={href} className={className} aria-label={unreadEmails ? `${label}, ${tip}` : label}>
                    <Icon className="size-4" />
                    {label}
                    {!!unreadEmails && (
                      <span className="ml-auto grid h-5 min-w-5 place-items-center rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-none text-primary-foreground">
                        {unreadEmails > 99 ? "99+" : unreadEmails}
                      </span>
                    )}
                  </Link>
                }
              />
              <TooltipContent side="right">{tip}</TooltipContent>
            </Tooltip>
          );
        }
        return (
          <Link key={href} href={href} className={className}>
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
      <div className="mt-auto rounded-md border p-3 text-xs">
        <div className="truncate font-medium">{user.name}</div>
        <div className="truncate text-muted-foreground">{user.email}</div>
        <div className="mt-1 text-muted-foreground">{roleLabel(user)}</div>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr] print:block">
      <aside className="sticky top-0 hidden h-screen border-r bg-card md:block print:hidden">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-card">{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center print:hidden justify-between border-b bg-background/80 px-4 backdrop-blur">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label="Menu" onClick={() => setOpen((o) => !o)}>
            {open ? <X className="size-4" /> : <Menu className="size-4" />}
          </Button>
          <div className="ml-auto flex items-center gap-1">
            <NotificationBell />
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={() => {
                leaving.current = true;
                signOut();
              }}>
              <LogOut className="mr-2 size-4" />
              Sign out
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4 md:p-8">{children}</main>
      </div>
      {/* the floating chat assistant, for every role, and never on paper; the Buyer Assistant page is already a chat */}
      {pathname !== "/assistant" && (
        <div className="print:hidden">
          <ChatWidget />
        </div>
      )}

    </div>
  );
}
