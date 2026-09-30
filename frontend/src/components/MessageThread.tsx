/**
 * Request message thread (SRS §3.1, §5.1): private chat between the buyer and one invited
 * supplier, with attachments.
 *
 *   - MessageThreadView: pure UI (messages + composer). Build and check it with mock data.
 *   - MessageThread: loads and sends through the API, polling every 10 s.
 *
 * Supplier text is untrusted (SRS §6.3): it is always rendered as plain text, never as HTML.
 */
import { FileText, ImageIcon, Loader2, Lock, Paperclip, Send, X } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- types (API contract)

export type Attachment = {
  id: number;
  fileName: string;
  fileType: string; // MIME type
  sizeBytes: number;
  url: string; // e.g. "/attachments/12"
};

export type ThreadMessage = {
  id: number;
  author: string; // user id
  authorName: string;
  authorRole: "buyer" | "supplier" | "inspector" | "admin";
  text: string;
  sentAt: string; // ISO 8601 UTC
  attachments: Attachment[];
};

export type ThreadInfo = {
  requestId: string;
  supplierId: string;
  supplierName: string;
  invitationStatus: "invited" | "declined" | "responded";
  canPost: boolean;
};

export type ThreadResponse = { thread: ThreadInfo; messages: ThreadMessage[] };

// ---------------------------------------------------------------- limits (match .env.example)

const POLL_MS = 10_000;
const MAX_FILES = 5;
const MAX_BYTES = 20 * 1024 * 1024; // MAX_UPLOAD_SIZE_MB=20
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp"; // ALLOWED_UPLOAD_EXTENSIONS
const MAX_CHARS = 5000;

function timeAgo(iso: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------------------------------------------------------------- view (no API calls)

type ViewProps = {
  thread: ThreadInfo | null; // null while loading
  messages: ThreadMessage[];
  currentUserId: string;
  loadError?: string | null;
  onRetry?: () => void;
  /** Send a message. Resolve with an error message to show, or null on success. */
  onSend: (text: string, files: File[]) => Promise<string | null>;
  onDownload: (attachment: Attachment) => Promise<void>;
};

export function MessageThreadView({
  thread,
  messages,
  currentUserId,
  loadError,
  onRetry,
  onSend,
  onDownload,
}: ViewProps) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // Keep the newest message in view.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const next = [...files, ...Array.from(list)];
    const tooBig = next.find((f) => f.size > MAX_BYTES);
    if (next.length > MAX_FILES) setSendError(`Attach up to ${MAX_FILES} files per message.`);
    else if (tooBig) setSendError(`${tooBig.name} is larger than 20 MB.`);
    else {
      setFiles(next);
      setSendError(null);
    }
    if (fileInput.current) fileInput.current.value = ""; // allow picking the same file again
  }

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const body = text.trim();
    if (!body && files.length === 0) {
      setSendError("Write a message or attach a file.");
      return;
    }
    setSending(true);
    const error = await onSend(body, files);
    setSending(false);
    if (error) {
      setSendError(error);
    } else {
      setText("");
      setFiles([]);
      setSendError(null);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  }

  if (loadError && !thread) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-sm">
        <p className="text-muted-foreground">{loadError}</p>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-lg border bg-card">
      <div className="border-b px-4 py-3">
        <p className="text-sm font-medium">{thread?.supplierName ?? "Loading…"}</p>
        <p className="text-xs text-muted-foreground">
          {thread?.requestId} · Private thread between the buyer and this supplier
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
        {thread && messages.length === 0 && (
          <p className="py-10 text-center text-sm text-muted-foreground">
            No messages yet. Questions and answers about this request go here.
          </p>
        )}
        {messages.map((m) => {
          const mine = m.author === currentUserId;
          return (
            <div key={m.id} className={cn("flex flex-col", mine ? "items-end" : "items-start")}>
              <div className="mb-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="font-medium text-foreground">{mine ? "You" : m.authorName}</span>
                <span className="capitalize">{m.authorRole}</span>
                <time dateTime={m.sentAt} title={new Date(m.sentAt).toLocaleString()}>
                  {timeAgo(m.sentAt)}
                </time>
              </div>
              <div
                className={cn(
                  "max-w-[80%] rounded-lg px-3 py-2 text-sm",
                  mine ? "bg-primary text-primary-foreground" : "border bg-background",
                )}
              >
                {m.text && <p className="break-words whitespace-pre-wrap">{m.text}</p>}
                {m.attachments.length > 0 && (
                  <ul className={cn("flex flex-col gap-1", m.text && "mt-2")}>
                    {m.attachments.map((a) => (
                      <AttachmentChip key={a.id} att={a} inverted={mine} onDownload={onDownload} />
                    ))}
                  </ul>
                )}
              </div>
            </div>
          );
        })}
        <div ref={bottom} />
      </div>

      {thread && !thread.canPost ? (
        <div className="flex items-center gap-2 border-t bg-muted px-4 py-3 text-xs text-muted-foreground">
          <Lock className="size-3.5" />
          {thread.invitationStatus === "declined"
            ? "The supplier declined this request. The thread is read-only."
            : "This thread is read-only."}
        </div>
      ) : (
        <form onSubmit={send} className="border-t p-3">
          {files.length > 0 && (
            <ul className="mb-2 flex flex-wrap gap-2">
              {files.map((f, i) => (
                <li
                  key={`${f.name}-${i}`}
                  className="flex items-center gap-1.5 rounded-md border bg-muted px-2 py-1 text-xs"
                >
                  <Paperclip className="size-3" />
                  <span className="max-w-[160px] truncate">{f.name}</span>
                  <span className="text-muted-foreground">{formatBytes(f.size)}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${f.name}`}
                    onClick={() => setFiles(files.filter((_, j) => j !== i))}
                    className="rounded p-0.5 hover:bg-background"
                  >
                    <X className="size-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-end gap-2">
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => addFiles(e.target.files)}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Attach files"
              onClick={() => fileInput.current?.click()}
            >
              <Paperclip />
            </Button>
            <textarea
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setSendError(null);
              }}
              onKeyDown={onKeyDown}
              rows={2}
              maxLength={MAX_CHARS}
              placeholder="Write a message. Enter to send, Shift+Enter for a new line"
              aria-label="Message"
              className="min-h-10 flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
            <Button type="submit" disabled={sending}>
              {sending ? <Loader2 className="animate-spin" /> : <Send />}
              Send
            </Button>
          </div>
          {sendError && (
            <p className="mt-2 text-xs text-destructive" role="alert">
              {sendError}
            </p>
          )}
        </form>
      )}
    </div>
  );
}

function AttachmentChip({
  att,
  inverted,
  onDownload,
}: {
  att: Attachment;
  inverted: boolean;
  onDownload: (a: Attachment) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const Icon = att.fileType.startsWith("image/") ? ImageIcon : FileText;

  async function download() {
    setBusy(true);
    try {
      await onDownload(att);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li>
      <button
        type="button"
        onClick={download}
        disabled={busy}
        className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs",
          inverted ? "bg-white/15 hover:bg-white/25" : "bg-muted hover:bg-accent",
        )}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Icon className="size-4 shrink-0" />}
        <span className="min-w-0 flex-1 truncate">{att.fileName}</span>
        <span className="opacity-70">{formatBytes(att.sizeBytes)}</span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------- connected (talks to the API)

const API_BASE = import.meta.env.VITE_API_BASE_URL;

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body?.error?.message ?? body?.detail ?? `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

async function fetchThread(
  requestId: string,
  supplierId: string,
  userId: string,
): Promise<ThreadResponse | string> {
  try {
    const res = await fetch(
      `${API_BASE}/requests/${encodeURIComponent(requestId)}/threads/${encodeURIComponent(supplierId)}/messages`,
      { headers: { "X-Portal-User": userId } },
    );
    return res.ok ? ((await res.json()) as ThreadResponse) : await readError(res);
  } catch {
    return "Can't reach the server. Check your connection and retry.";
  }
}

type Props = {
  requestId: string;
  supplierId: string;
  userId: string; // from the role picker; sent as X-Portal-User
};

export function MessageThread({ requestId, supplierId, userId }: Props) {
  const [data, setData] = useState<ThreadResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const apply = useCallback((result: ThreadResponse | string) => {
    if (typeof result === "string") {
      setLoadError(result);
    } else {
      setData(result);
      setLoadError(null);
    }
  }, []);

  const refresh = useCallback(() => {
    void fetchThread(requestId, supplierId, userId).then(apply);
  }, [requestId, supplierId, userId, apply]);

  // Load now, then every 10 s while the tab is visible.
  useEffect(() => {
    let active = true;
    const load = () =>
      fetchThread(requestId, supplierId, userId).then((result) => {
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
  }, [requestId, supplierId, userId, apply]);

  async function send(text: string, files: File[]): Promise<string | null> {
    // Multipart upload uses plain fetch so the browser sets the multipart boundary header.
    const form = new FormData();
    form.set("text", text);
    files.forEach((f) => form.append("files", f));
    try {
      const res = await fetch(
        `${API_BASE}/requests/${encodeURIComponent(requestId)}/threads/${encodeURIComponent(supplierId)}/messages`,
        { method: "POST", headers: { "X-Portal-User": userId }, body: form },
      );
      if (!res.ok) return await readError(res);
      const msg = (await res.json()) as ThreadMessage;
      setData((d) => (d ? { ...d, messages: [...d.messages, msg] } : d));
      return null;
    } catch {
      return "Couldn't send. Check your connection and try again.";
    }
  }

  async function download(att: Attachment) {
    // A plain <a href> can't send the X-Portal-User header, so fetch the file as a blob.
    const res = await fetch(`${API_BASE}${att.url}`, { headers: { "X-Portal-User": userId } });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = att.fileName;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }

  return (
    <MessageThreadView
      thread={data?.thread ?? null}
      messages={data?.messages ?? []}
      currentUserId={userId}
      loadError={loadError}
      onRetry={refresh}
      onSend={send}
      onDownload={download}
    />
  );
}
