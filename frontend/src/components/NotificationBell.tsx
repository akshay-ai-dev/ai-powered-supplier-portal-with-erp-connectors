/**
 * Notification bell (SRS §3.1): unread badge + dropdown list of the current user's notifications.
 *
 * Two components in one file:
 *   - NotificationBellView: pure UI. Takes data and callbacks as props, so it can be built and
 *     checked with mock data before the backend exists.
 *   - NotificationBell: connects the view to the API (GET /notifications, POST .../read).
 */
import {
  AlertTriangle,
  Award,
  Bell,
  CheckCheck,
  ClipboardCheck,
  Clock,
  FileText,
  type LucideIcon,
  MessageSquare,
  PackageCheck,
  Truck,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- types (API contract)

export type NotificationItem = {
  id: number;
  event: string; // one of the 10 events in SRS §3.1, e.g. "awarded"
  title: string;
  body: string;
  link: string; // portal path, e.g. "/requests/REQ-0007"
  read: boolean;
  createdAt: string; // ISO 8601 UTC
};

export type NotificationList = { unreadCount: number; items: NotificationItem[] };

// ---------------------------------------------------------------- helpers

const POLL_MS = 15_000;

const EVENT_STYLE: Record<string, { icon: LucideIcon; tone: string }> = {
  invited: { icon: FileText, tone: "bg-blue-50 text-blue-700" },
  response_received: { icon: FileText, tone: "bg-blue-50 text-blue-700" },
  awarded: { icon: Award, tone: "bg-green-50 text-green-700" },
  not_awarded: { icon: XCircle, tone: "bg-muted text-muted-foreground" },
  shipment_submitted: { icon: Truck, tone: "bg-blue-50 text-blue-700" },
  arrived: { icon: PackageCheck, tone: "bg-blue-50 text-blue-700" },
  inspection_result: { icon: ClipboardCheck, tone: "bg-green-50 text-green-700" },
  deadline_reached: { icon: Clock, tone: "bg-amber-50 text-amber-700" },
  erp_change_flagged: { icon: AlertTriangle, tone: "bg-amber-50 text-amber-700" },
  new_message: { icon: MessageSquare, tone: "bg-violet-50 text-violet-700" },
};

function timeAgo(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 172800) return "Yesterday";
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

// ---------------------------------------------------------------- view (no API calls)

type ViewProps = {
  unreadCount: number;
  items: NotificationItem[];
  error?: string | null;
  onSelect: (item: NotificationItem) => void;
  onMarkAllRead: () => void;
  onOpen?: () => void; // e.g. refresh when the list opens
  onRetry?: () => void;
};

export function NotificationBellView({
  unreadCount,
  items,
  error,
  onSelect,
  onMarkAllRead,
  onOpen,
  onRetry,
}: ViewProps) {
  const [open, setOpen] = useState(false);
  const badge = unreadCount > 99 ? "99+" : String(unreadCount);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) onOpen?.();
  }

  function select(item: NotificationItem) {
    setOpen(false);
    onSelect(item);
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={unreadCount ? `Notifications, ${unreadCount} unread` : "Notifications"}
        >
          <Bell className="size-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] rounded-full bg-destructive px-1 text-center text-[11px] leading-[18px] font-medium text-white">
              {badge}
            </span>
          )}
        </Button>
      </PopoverTrigger>

      <PopoverContent align="end" className="w-[380px] p-0">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <p className="text-sm font-medium">Notifications</p>
          {unreadCount > 0 && (
            <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={onMarkAllRead}>
              <CheckCheck /> Mark all as read
            </Button>
          )}
        </div>

        <div className="max-h-[420px] overflow-y-auto">
          {error ? (
            <div className="px-4 py-8 text-center text-sm">
              <p className="text-muted-foreground">{error}</p>
              {onRetry && (
                <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
                  Retry
                </Button>
              )}
            </div>
          ) : items.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <Bell className="mx-auto size-6 text-muted-foreground" />
              <p className="mt-2 text-sm font-medium">You're all caught up</p>
              <p className="text-xs text-muted-foreground">
                Updates on your requests will show up here.
              </p>
            </div>
          ) : (
            <ul>
              {items.map((n) => {
                const { icon: Icon, tone } = EVENT_STYLE[n.event] ?? EVENT_STYLE.invited;
                return (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => select(n)}
                      className={cn(
                        "flex w-full gap-3 border-b px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-accent",
                        !n.read && "bg-blue-50/40",
                      )}
                    >
                      <span
                        className={cn(
                          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full",
                          tone,
                        )}
                      >
                        <Icon className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={cn("block text-sm", !n.read && "font-medium")}>
                          {n.title}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {n.body}
                        </span>
                        <span className="mt-1 block text-[11px] text-muted-foreground">
                          {timeAgo(n.createdAt)}
                        </span>
                      </span>
                      {!n.read && (
                        <span
                          className="mt-2 size-2 shrink-0 rounded-full bg-blue-600"
                          aria-label="Unread"
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ---------------------------------------------------------------- connected (talks to the API)

type Props = {
  userId: string; // from the role picker; sent as X-Portal-User
  onNavigate: (link: string) => void; // open the record behind a notification
};

async function fetchNotifications(userId: string): Promise<NotificationList | null> {
  const { data, error } = await api.GET("/notifications", {
    params: { query: { limit: 20 } },
    headers: { "X-Portal-User": userId },
  });
  return error || !data ? null : (data as NotificationList);
}

export function NotificationBell({ userId, onNavigate }: Props) {
  const [data, setData] = useState<NotificationList>({ unreadCount: 0, items: [] });
  const [error, setError] = useState<string | null>(null);
  const headers = { "X-Portal-User": userId };

  const apply = useCallback((result: NotificationList | null) => {
    if (result) {
      setData(result);
      setError(null);
    } else {
      setError("Couldn't load notifications");
    }
  }, []);

  const refresh = useCallback(() => {
    void fetchNotifications(userId).then(apply);
  }, [userId, apply]);

  // Load now, then every 15 s while the tab is visible. State is set in the promise
  // callback (not directly in the effect), and ignored after unmount or user change.
  useEffect(() => {
    let active = true;
    const load = () =>
      fetchNotifications(userId).then((result) => {
        if (active) apply(result);
      });
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [userId, apply]);

  async function select(item: NotificationItem) {
    if (!item.read) {
      // Optimistic: update the UI first, then tell the server.
      setData((d) => ({
        unreadCount: Math.max(0, d.unreadCount - 1),
        items: d.items.map((x) => (x.id === item.id ? { ...x, read: true } : x)),
      }));
      const { error } = await api.POST("/notifications/{id}/read", {
        params: { path: { id: item.id } },
        headers,
      });
      if (error) void refresh(); // roll back to the server's view
    }
    onNavigate(item.link);
  }

  async function markAllRead() {
    setData((d) => ({ unreadCount: 0, items: d.items.map((x) => ({ ...x, read: true })) }));
    const { error } = await api.POST("/notifications/read-all", { headers });
    if (error) void refresh();
  }

  return (
    <NotificationBellView
      unreadCount={data.unreadCount}
      items={data.items}
      error={error}
      onSelect={select}
      onMarkAllRead={markAllRead}
      onOpen={refresh}
      onRetry={refresh}
    />
  );
}
