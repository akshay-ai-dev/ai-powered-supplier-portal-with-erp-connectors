"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Bot, Check, ChevronLeft, Loader2, MessageCircle, Send, SkipForward, X } from "lucide-react";
import { toast } from "sonner";
import { api, uploadFile } from "@/lib/api";
import type { AssistantResponse, ChatReply } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { AnswerView } from "@/components/assistant/answer-templates";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Line =
  | { from: "bot" | "me"; text: string; error?: boolean; link?: { href: string; label: string }; asked?: boolean }
  | { from: "answer"; reply: ChatReply };
interface Saved {
  resp: AssistantResponse | null;
  lines: Line[];
}

const SHOWN = 30; // chat lines kept on screen
const HISTORY = 10; // earlier ask-box turns sent with a question
const storeKey = (id: number) => `erp_chat_assistant_v3_${id}`;

/** The conversation GPT-4o sees: earlier questions and the tools called with their arguments. Tool results are never
 *  sent back to the model (SRS §6.3: they are data, never instructions), and the numbered-menu turns are left out. */
type Turn = { role: "user"; content: string } | { role: "assistant"; tool: string; args: Record<string, unknown> };
function chatHistory(lines: Line[]): Turn[] {
  const turns = lines.flatMap((l): Turn[] => {
    if (l.from === "me" && l.asked) return [{ role: "user", content: l.text }];
    if (l.from === "answer" && l.reply.tool) return [{ role: "assistant", tool: l.reply.tool, args: l.reply.args ?? {} }];
    return [];
  });
  return turns.slice(-HISTORY);
}
const loadSaved = (id: number): Saved => {
  try {
    const raw = sessionStorage.getItem(storeKey(id));
    if (raw) return JSON.parse(raw) as Saved;
  } catch {
    /* private mode or corrupt value: start fresh */
  }
  return { resp: null, lines: [] };
};

/**
 * Floating assistant, for every role: numbered menus that ask one question at a time and save only after you confirm.
 * On the menu screen every role can also ask in its own words: GPT-4o picks one of that role's MCP tools on the
 * backend and the tool's result is shown as it is. Drafts are saved only when the user confirms them in the card.
 */
export function ChatWidget() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [resp, setResp] = useState<AssistantResponse | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const file = useRef<File | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const userId = user?.id;

  useEffect(() => {
    if (userId == null) return;
    const saved = loadSaved(userId);
    setResp(saved.resp);
    setLines(saved.lines);
  }, [userId]);
  useEffect(() => {
    if (userId == null) return;
    try {
      sessionStorage.setItem(storeKey(userId), JSON.stringify({ resp, lines: lines.slice(-60) }));
    } catch {
      /* storage unavailable: the conversation just is not remembered */
    }
  }, [userId, resp, lines]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [lines, resp, open]);

  if (!user) return null;

  const fail = (err: unknown, echo?: string) => {
    const message = err instanceof Error ? err.message : "Something went wrong";
    setLines((l) => [...l, ...(echo ? [{ from: "me" as const, text: echo }] : []), { from: "bot", text: message, error: true }]);
    toast.error(message);
  };

  /** One turn of the numbered-menu conversation. */
  async function send(input: string | null, echo?: string, fresh = false) {
    setBusy(true);
    try {
      const state = !fresh && resp ? resp.state : null;
      const next = await api<AssistantResponse>("/api/assistant/step", { body: { state, input, tz_offset: new Date().getTimezoneOffset() } });
      const add: Line[] = [];
      if (echo) add.push({ from: "me", text: echo });
      if (next.result) {
        add.push({ from: "bot", text: `${next.result.label}.`, link: { href: next.result.href, label: "Open it" } });
        const upload = next.result.upload;
        if (upload && file.current) {
          try {
            await uploadFile(upload, file.current);
            add.push({ from: "bot", text: "Packing list attached." });
          } catch (err) {
            add.push({ from: "bot", text: `The packing list was not attached (${err instanceof Error ? err.message : "failed"}). Add it from the shipment page.`, error: true });
          }
        }
      }
      if (next.stage === "menu") file.current = null; // keep the chosen file until the order is submitted or abandoned
      if (next.error) add.push({ from: "bot", text: next.error, error: true });
      add.push({ from: "bot", text: next.message });
      setLines((l) => [...l, ...add]);
      setResp(next);
      setText("");
      setPicked([]);
    } catch (err) {
      fail(err, echo);
    } finally {
      setBusy(false);
    }
  }

  /** A question on the menu screen: the backend asks GPT-4o for one tool, runs it, and returns its result. */
  async function ask(question: string) {
    setBusy(true);
    setText("");
    const history = chatHistory(lines);
    setLines((l) => [...l, { from: "me", text: question, asked: true }]);
    try {
      const reply = await api<ChatReply>("/api/assistant/chat", { body: { message: question, history, tz_offset: new Date().getTimezoneOffset() } });
      setLines((l) => [...l, { from: "answer", reply }]);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  const startOver = () => {
    file.current = null;
    setLines([]);
    setResp(null);
    void send(null, undefined, true);
  };
  const toggle = () => {
    setOpen((o) => !o);
    if (!open && !resp && !busy) void send(null, undefined, true);
  };

  const menuMode = resp?.stage === "menu";
  const freeText = resp?.stage === "step" && resp.kind !== "choice" && resp.kind !== "multichoice" && resp.kind !== "file";
  const asking = menuMode; // every role can ask on the menu screen; the numbered options stay above the box
  const isNumber = /^\d+$/.test(text.trim());

  function submitText(e: React.FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    if (asking && !isNumber) void ask(value);
    else void send(value, value); // a menu number, or the answer to the current question
  }

  const offset = Math.max(0, lines.length - SHOWN);

  const optionButtons = (opts: { key: string; label: string }[], more: boolean | undefined, onPick: (key: string, label: string) => void, onMore: () => void) => (
    <div className="max-h-44 space-y-1 overflow-y-auto">
      {opts.map((o) => (
        <Button key={o.key} variant="outline" size="sm" disabled={busy} className="h-auto w-full justify-start whitespace-normal py-1.5 text-left" onClick={() => onPick(o.key, o.label)}>
          <span className="mr-2 font-mono text-xs text-muted-foreground">{o.key}</span>
          {o.label}
        </Button>
      ))}
      {more && (
        <Button variant="ghost" size="sm" disabled={busy} className="w-full" onClick={onMore}>
          <span className="mr-2 font-mono text-xs">9</span> More options
        </Button>
      )}
    </div>
  );

  return (
    <>
      {open && (
        <div role="dialog" aria-label="Chat assistant" className="fixed inset-x-2 bottom-20 z-50 flex max-h-[min(38rem,calc(100vh-6rem))] flex-col overflow-hidden rounded-xl border bg-card shadow-xl sm:inset-x-auto sm:right-4 sm:w-96">
          <div className="flex items-center gap-2 border-b px-4 py-3">
            <Bot className="size-4" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold">Chat assistant{resp?.title ? ` - ${resp.title}` : ""}</div>
              {resp?.progress && resp.stage !== "menu" && (
                <div className="text-xs text-muted-foreground">Step {Math.min(resp.progress.done + 1, resp.progress.total)} of {resp.progress.total}</div>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={startOver} disabled={busy}>Start over</Button>
            <Button variant="ghost" size="icon" aria-label="Close chat assistant" onClick={() => setOpen(false)}>
              <X className="size-4" />
            </Button>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3 text-sm">
            {lines.slice(offset).map((l, i) =>
              l.from === "answer" ? (
                <div key={offset + i} className="space-y-1">
                  {l.reply.tool && <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">used: {l.reply.tool}</span>}
                  <AnswerView reply={l.reply} onNavigate={() => setOpen(false)} />
                </div>
              ) : (
                <div key={offset + i} className={l.from === "me" ? "flex justify-end" : "flex"}>
                  <div className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 ${l.from === "me" ? "bg-primary text-primary-foreground" : l.error ? "bg-destructive/10 text-destructive" : "bg-muted"}`}>
                    {l.text}
                    {l.link && (
                      <>
                        {" "}
                        <Link href={l.link.href} className="font-medium underline" onClick={() => setOpen(false)}>
                          {l.link.label}
                        </Link>
                      </>
                    )}
                  </div>
                </div>
              ),
            )}
            {busy && asking && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
            {resp?.stage === "summary" && resp.summary && (
              <div className="rounded-lg border p-3">
                {resp.summary.map((s) => (
                  <div key={s.label} className="flex justify-between gap-3 py-0.5">
                    <span className="shrink-0 text-muted-foreground">{s.label}</span>
                    <span className="text-right font-medium">{s.value}</span>
                  </div>
                ))}
              </div>
            )}
            {resp?.stage === "summary" && resp.warning && <p className="rounded-md bg-amber-500/15 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">{resp.warning}</p>}
            {resp?.hint && resp.stage === "step" && <p className="text-xs text-muted-foreground">{resp.hint}</p>}
            <div ref={bottom} />
          </div>

          <div className="space-y-2 border-t p-3">
            {/* ---- numbered menus (every role) */}
            {resp && (resp.kind === "choice" || resp.stage === "menu") && resp.options.length > 0 &&
              optionButtons(resp.options, resp.controls.more, (k, label) => void send(k, label), () => void send("9", "More"))}

            {resp?.kind === "multichoice" && (
              <div className="space-y-1">
                <div className="max-h-36 space-y-1 overflow-y-auto">
                  {resp.options.map((o) => (
                    <label key={o.key} className="flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-sm">
                      <input type="checkbox" checked={picked.includes(o.key)} onChange={() => setPicked((p) => (p.includes(o.key) ? p.filter((k) => k !== o.key) : [...p, o.key]))} />
                      {o.label}
                    </label>
                  ))}
                </div>
                <div className="flex gap-2">
                  <Button size="sm" disabled={busy || picked.length === 0} onClick={() => void send(picked.join(","), resp.options.filter((o) => picked.includes(o.key)).map((o) => o.label).join(", "))}>
                    Send selection
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void send("all", "All")}>
                    All
                  </Button>
                </div>
              </div>
            )}

            {resp?.kind === "file" && (
              <label className="block text-sm">
                <span className="sr-only">Packing list</span>
                <input
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.doc,.docx,.txt"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      file.current = f;
                      void send("attached", `Attached ${f.name}`);
                    }
                  }}
                  className="block w-full text-xs file:mr-2 file:rounded-md file:border file:bg-background file:px-2 file:py-1"
                />
              </label>
            )}

            {(freeText || resp?.kind === "choice") && (
              <form onSubmit={submitText} className="flex gap-2">
                <Input
                  aria-label="Your answer"
                  value={text}
                  disabled={busy}
                  onChange={(e) => setText(e.target.value)}
                  type={resp?.kind === "date" ? "date" : resp?.kind === "datetime" ? "datetime-local" : "text"}
                  inputMode={resp?.kind === "int" ? "numeric" : resp?.kind === "number" ? "decimal" : undefined}
                  placeholder={resp?.kind === "choice" ? "Type to search the list" : "Type your answer"}
                />
                <Button type="submit" size="icon" aria-label="Send" disabled={busy || !text.trim()}>
                  <Send className="size-4" />
                </Button>
              </form>
            )}

            {resp && resp.stage !== "menu" && (
              <div className="flex flex-wrap gap-2">
                {resp.controls.confirm && (
                  <Button size="sm" disabled={busy} onClick={() => void send("#", "Confirm")}>
                    <Check className="mr-1 size-4" />
                    Confirm
                  </Button>
                )}
                {resp.controls.skip && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void send("#", "Skip")}>
                    <SkipForward className="mr-1 size-4" />
                    Skip
                  </Button>
                )}
                {resp.controls.back && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void send(resp.kind === "choice" || resp.kind === "multichoice" || resp.stage === "summary" ? "0" : "back", "Back")}>
                    <ChevronLeft className="mr-1 size-4" />
                    Back
                  </Button>
                )}
                {resp.controls.cancel && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void send("*", "Cancel")}>
                    Cancel
                  </Button>
                )}
              </div>
            )}

            {/* ---- ask in your own words (menu screen, every role) */}
            {asking && (
              <form onSubmit={submitText} className="flex items-center gap-2">
                <Input
                  aria-label="Ask the assistant"
                  className="min-w-0 flex-1"
                  value={text}
                  disabled={busy}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={500}
                  placeholder="Ask a question, or type a menu number…"
                />
                <Button type="submit" size="icon" aria-label="Send" disabled={busy || !text.trim()}>
                  <Send className="size-4" />
                </Button>
              </form>
            )}
          </div>
        </div>
      )}
      <Button type="button" size="icon" aria-label={open ? "Close chat assistant" : "Open chat assistant"} onClick={toggle} className="fixed bottom-4 right-4 z-50 size-12 rounded-full shadow-lg">
        {open ? <X className="size-5" /> : <MessageCircle className="size-5" />}
      </Button>
    </>
  );
}
