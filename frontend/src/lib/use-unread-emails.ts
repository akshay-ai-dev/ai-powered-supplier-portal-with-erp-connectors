"use client";
import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";

const POLL_MS = 30_000;
/** Fire `window.dispatchEvent(new Event(EMAILS_CHANGED))` after an email is opened so the count updates at once. */
export const EMAILS_CHANGED = "emails:changed";

/** Number of unread emails for the signed-in user; null while unknown or if the mail service is unreachable. */
export function useUnreadEmails(enabled = true): number | null {
  const pathname = usePathname();
  const [unread, setUnread] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      setUnread((await api<{ unread: number }>("/api/emails/unread-count")).unread);
    } catch {
      setUnread(null); // Mailpit down: show no badge rather than an error in the sidebar
    }
  }, [enabled]);

  useEffect(() => {
    refresh();
  }, [refresh, pathname]);

  useEffect(() => {
    const tick = () => document.visibilityState === "visible" && refresh();
    const id = window.setInterval(tick, POLL_MS);
    window.addEventListener("focus", refresh);
    window.addEventListener(EMAILS_CHANGED, refresh);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(EMAILS_CHANGED, refresh);
    };
  }, [refresh]);

  return unread;
}