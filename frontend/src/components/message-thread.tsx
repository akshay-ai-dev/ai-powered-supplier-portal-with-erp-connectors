"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Paperclip, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api, dateTime, downloadFile, fileSize, uploadFile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface MessageFile {
  id: number;
  filename: string;
  size: number;
}
interface Message {
  id: number;
  body: string;
  sender_role: "buyer" | "supplier";
  sender_name: string | null;
  created_at: string;
  mine: boolean;
  attachments: MessageFile[];
}
interface Thread {
  supplier_id: number;
  supplier_name: string;
  can_post: boolean;
  messages: Message[];
}

const POLL_MS = 8000;
// Same rules as the server (services/attachments.py); the server checks again.
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.gif,.webp,.dwg,.dxf,.step,.stp,.xlsx,.xls,.csv,.txt,.docx,.zip";
const MAX_BYTES = 10 * 1024 * 1024;

/** One buyer<->supplier conversation. Buyers pass `supplierId`; suppliers omit it (the server uses their own). */
export function MessageThread({ requirementId, supplierId, onActivity }: { requirementId: number; supplierId?: number; onActivity?: () => void }) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
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

  function pickFile(f: File | undefined) {
    if (!f) return;
    if (f.size > MAX_BYTES) {
      toast.error(`${f.name} is larger than 10 MB`);
      return;
    }
    setFile(f);
  }

  async function send() {
    const body = draft.trim();
    if (!body && !file) return;
    setSending(true);
    try {
      const t = file
        ? await uploadFile<Thread>(`/api/requirements/${requirementId}/messages/attachments`, file, { body, supplier_id: supplierId })
        : await api<Thread>(`/api/requirements/${requirementId}/messages`, { body: { body, supplier_id: supplierId } });
      setThread(t);
      count.current = t.messages.length;
      setDraft("");
<<<<<<< HEAD
      onActivity?.();
=======
      setFile(null);
>>>>>>> main
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
              {m.body && <div className="whitespace-pre-wrap break-words">{m.body}</div>}
              {m.attachments?.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => downloadFile(`/api/message-attachments/${a.id}/download`, a.filename).catch((e) => toast.error(e.message))}
                  className={`mt-1 flex max-w-full items-center gap-2 rounded-md border px-2 py-1 text-left text-xs ${m.mine ? "border-primary-foreground/30 hover:bg-primary-foreground/10" : "hover:bg-accent"}`}
                  aria-label={`Download ${a.filename}`}
                >
                  <Paperclip className="size-3.5 shrink-0" />
                  <span className="truncate">{a.filename}</span>
                  <span className="shrink-0 opacity-70">{fileSize(a.size)}</span>
                  <Download className="size-3.5 shrink-0" />
                </button>
              ))}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {thread.can_post ? (
        <div className="space-y-2">
          {file && (
            <div className="flex w-fit max-w-full items-center gap-2 rounded-md border bg-muted/40 px-2 py-1 text-xs">
              <Paperclip className="size-3.5 shrink-0" />
              <span className="truncate">{file.name}</span>
              <span className="shrink-0 text-muted-foreground">{fileSize(file.size)}</span>
              <button type="button" aria-label="Remove file" onClick={() => setFile(null)} className="rounded p-0.5 hover:bg-accent">
                <X className="size-3.5" />
              </button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                pickFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <Button type="button" variant="outline" size="icon" aria-label="Attach a file" title="Attach a file (PDF, image, DWG/DXF/STEP, Office, CSV, ZIP; max 10 MB)" disabled={sending} onClick={() => fileInput.current?.click()}>
              <Paperclip className="size-4" />
            </Button>
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
            <Button onClick={send} disabled={sending || (!draft.trim() && !file)}>
              <Send className="mr-1 size-4" />
              Send
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">This conversation is closed. You can still read it.</p>
      )}
    </div>
  );
}
