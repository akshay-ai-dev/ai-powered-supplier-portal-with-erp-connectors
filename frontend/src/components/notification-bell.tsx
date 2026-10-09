"use client";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const POLL_MS = 30_000;
/** Any page can call `window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED))` to refresh the bell right away. */
export const NOTIFICATIONS_CHANGED = "notifications:changed";

function timeAgo(iso: string): string {
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days < 7 ? `${days}d ago` : new Date(iso).toLocaleDateString();
}

export function NotificationBell() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Notification[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshCount = useCallback(async () => {
    try {
      const { unread } = await api<{ unread: number }>("/api/notifications/unread-count");
      setUnread(unread);
    } catch {
      /* the bell must never break the page; the next poll retries */
    }
  }, []);

  const loadList = useCallback(async () => {
    try {
      setItems(await api<Notification[]>("/api/notifications?limit=20"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load notifications");
    }
  }, []);

  // Badge: on mount, every page change, every 30 s while the tab is visible, on tab focus, and on demand.
  useEffect(() => {
    refreshCount();
  }, [refreshCount, pathname]);
  useEffect(() => {
    const tick = () => document.visibilityState === "visible" && refreshCount();
    const id = window.setInterval(tick, POLL_MS);
    window.addEventListener("focus", refreshCount);
    window.addEventListener(NOTIFICATIONS_CHANGED, refreshCount);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", refreshCount);
      window.removeEventListener(NOTIFICATIONS_CHANGED, refreshCount);
    };
  }, [refreshCount]);

  // List: fetched fresh every time the panel opens.
  useEffect(() => {
    if (open) loadList();
  }, [open, loadList]);

  async function openItem(n: Notification) {
    if (!n.is_read) {
      setItems((list) => list?.map((x) => (x.id === n.id ? { ...x, is_read: 1 } : x)) ?? null);
      setUnread((u) => Math.max(0, u - 1));
      api(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(refreshCount);
    }
    setOpen(false);
    if (n.link) router.push(n.link);
  }

  async function markAllRead() {
    setItems((list) => list?.map((x) => ({ ...x, is_read: 1 })) ?? null);
    setUnread(0);
    try {
      await api("/api/notifications/read-all", { method: "POST" });
    } catch {
      refreshCount();
    }
  }

  const label = unread > 0 ? `Notifications, ${unread} unread` : "Notifications";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button variant="ghost" size="icon" aria-label={label} className="relative">
            <Bell className="size-4" />
            {unread > 0 && (
              <span className="absolute -top-0.5 -right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] leading-none font-semibold text-white">
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </Button>
        }
      />
      <PopoverContent align="end" className="flex w-[min(24rem,calc(100vw-2rem))] flex-col">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <PopoverTitle>Notifications</PopoverTitle>
          <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={unread === 0} onClick={markAllRead}>
            <CheckCheck className="mr-1 size-3.5" />
            Mark all read
          </Button>
        </div>
        <div className="max-h-[min(28rem,70vh)] overflow-y-auto">
          {error && <p className="p-4 text-sm text-destructive">{error}</p>}
          {!error && items === null && <p className="p-4 text-sm text-muted-foreground">Loading…</p>}
          {!error && items?.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">You&apos;re all caught up.</p>
          )}
          {items?.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => openItem(n)}
              className={cn(
                "flex w-full gap-3 border-b px-4 py-3 text-left transition-colors last:border-0 hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
                !n.is_read && "bg-primary/5"
              )}
            >
              <span
                aria-hidden
                className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.is_read ? "bg-transparent" : "bg-primary")}
              />
              <span className="min-w-0 flex-1">
                <span className={cn("block text-sm", !n.is_read && "font-medium")}>{n.title}</span>
                <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">{n.message}</span>
                <span className="mt-1 block text-[11px] text-muted-foreground">{timeAgo(n.created_at)}</span>
              </span>
              {!n.is_read && <span className="sr-only">Unread</span>}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
