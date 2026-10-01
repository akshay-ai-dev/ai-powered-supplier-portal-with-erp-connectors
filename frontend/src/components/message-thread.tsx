"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface Message {
  id: number;
  body: string;
  sender_role: "buyer" | "supplier";
  sender_name: string | null;
  created_at: string;
  mine: boolean;
}
interface Thread {
  supplier_id: number;
  supplier_name: string;
  can_post: boolean;
  messages: Message[];
}

const POLL_MS = 8000;

/** One buyer<->supplier conversation. Buyers pass `supplierId`; suppliers omit it (the server uses their own). */
export function MessageThread({ requirementId, supplierId, onActivity }: { requirementId: number; supplierId?: number; onActivity?: () => void }) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const count = useRef(0);
  const query = supplierId ? `?supplier_id=${supplierId}` : "";
  const path = `/api/requirements/${requirementId}/messages${query}`;

  const load = useCallback(async () => {
    try {
      const t = await api<Thread>(path);
      setThread(t);
      setError(null);
      if (t.messages.length !== count.current) {
        const first = count.current === 0;
        count.current = t.messages.length;
        if (!first) onActivity?.();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load messages");
    }
  }, [path, onActivity]);

  // Reset when switching thread, then refresh every few seconds while the tab is visible ("live" without websockets).
  useEffect(() => {
    setThread(null);
    count.current = 0;
    load();
    const t = setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [thread?.messages.length]);

  async function send() {
    const body = draft.trim();
    if (!body) return;
    setSending(true);
    try {
      const t = await api<Thread>(`/api/requirements/${requirementId}/messages`, { body: { body, supplier_id: supplierId } });
      setThread(t);
      count.current = t.messages.length;
      setDraft("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not send");
    } finally {
      setSending(false);
    }
  }

  if (error && !thread) return <p className="text-sm text-destructive">{error}</p>;
  if (!thread) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-3">
      <div className="max-h-80 min-h-24 space-y-2 overflow-y-auto rounded-md border bg-muted/30 p-3" aria-live="polite">
        {thread.messages.length === 0 && <p className="text-sm text-muted-foreground">No messages yet. Ask a question or send an update.</p>}
        {thread.messages.map((m) => (
          <div key={m.id} className={`flex ${m.mine ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.mine ? "bg-primary text-primary-foreground" : "border bg-card"}`}>
              <div className={`mb-0.5 text-xs ${m.mine ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
                {m.mine ? "You" : m.sender_name ?? m.sender_role} · {dateTime(m.created_at)}
              </div>
              <div className="whitespace-pre-wrap break-words">{m.body}</div>
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {thread.can_post ? (
        <div className="flex items-end gap-2">
          <Textarea
            aria-label="Message"
            value={draft}
            maxLength={2000}
            placeholder="Write a message… (Ctrl+Enter to send)"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
            }}
            className="min-h-16"
          />
          <Button onClick={send} disabled={sending || !draft.trim()}>
            <Send className="mr-1 size-4" />
            Send
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">This conversation is closed. You can still read it.</p>
      )}
    </div>
  );
}
