"use client";
import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorNote } from "@/components/page-header";

interface Thread {
  can_post: boolean;
  messages: { id: number; body: string; sender_name: string; created_at: string; mine: boolean }[];
}

export function TeamMessageThread({ inspectorId }: { inspectorId: number }) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const path = `/api/team/${inspectorId}/messages`;

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const next = await api<Thread>(path);
        if (active) { setThread(next); setError(null); }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Could not load messages");
      }
    }
    void load();
    const timer = setInterval(() => { if (document.visibilityState === "visible") void load(); }, 8000);
    return () => { active = false; clearInterval(timer); };
  }, [path]);

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [thread?.messages.length]);

  async function send() {
    if (sending || !draft.trim() || !thread?.can_post) return;
    setSending(true);
    try {
      setThread(await api<Thread>(path, { body: { body: draft.trim() } }));
      setDraft("");
      setError(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not send message");
    } finally { setSending(false); }
  }

  return (
    <div className="space-y-3">
      <ErrorNote message={error} />
      {!thread && !error && <p className="text-sm text-muted-foreground">Loading messages…</p>}
      {thread && <>
        <div className="max-h-96 min-h-40 space-y-3 overflow-y-auto rounded-md border bg-muted/30 p-3" aria-live="polite">
          {thread.messages.length === 0 && <p className="text-sm text-muted-foreground">No messages yet. Send a question or an update.</p>}
          {thread.messages.map((m) => (
            <div key={m.id} className={`flex ${m.mine ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${m.mine ? "bg-primary text-primary-foreground" : "border bg-card"}`}>
                <div className="mb-1 text-xs opacity-70">{m.mine ? "You" : m.sender_name} · {dateTime(m.created_at)}</div>
                <div className="whitespace-pre-wrap break-words">{m.body}</div>
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
        {thread.can_post ? (
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void send(); }}>
            <Textarea aria-label="Message" placeholder="Write a message… (Ctrl+Enter to send)" maxLength={2000} value={draft} disabled={sending}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void send(); } }} />
            <Button type="submit" disabled={sending || !draft.trim()}><Send className="mr-1 size-4" />Send</Button>
          </form>
        ) : <p className="text-sm text-muted-foreground">This account is disabled. You can still read the conversation.</p>}
      </>}
    </div>
  );
}
