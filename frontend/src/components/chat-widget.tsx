"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Bot, Check, ChevronLeft, ExternalLink, MessageCircle, Send, SkipForward, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api, uploadFile } from "@/lib/api";
import type { AssistantResponse, FillResponse } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { usePrefill } from "@/lib/prefill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type Resp = AssistantResponse | FillResponse;
type Line = { from: "bot" | "me"; text: string; error?: boolean; link?: { href: string; label: string } };
interface Saved {
  resp: Resp | null;
  lines: Line[];
  ai: boolean;
}

const isFill = (r: Resp | null): r is FillResponse => !!r && "mode" in r && r.mode === "fill";
const storeKey = (id: number) => `erp_chat_assistant_${id}`;
const loadSaved = (id: number): Saved => {
  try {
    const raw = sessionStorage.getItem(storeKey(id));
    if (raw) return JSON.parse(raw) as Saved;
  } catch {
    /* private mode or corrupt value: start fresh */
  }
  return { resp: null, lines: [], ai: false };
};

/** The form the user is looking at, if the assistant can fill it. */
function pageForm(pathname: string, role: string): { form: string; target?: number } | null {
  const buyer = role === "buyer" || role === "admin";
  if (buyer && pathname === "/requirements/new") return { form: "new_requirement" };
  if (buyer && pathname === "/purchase-orders/new") return { form: "new_purchase_order" };
  const req = pathname.match(/^\/requirements\/(\d+)$/);
  if (role === "supplier" && req) return { form: "submit_quote", target: Number(req[1]) };
  const po = pathname.match(/^\/purchase-orders\/(\d+)$/);
  if (role === "supplier" && po) return { form: "ship_order", target: Number(po[1]) };
  return null;
}

/**
 * Floating assistant. Two ways to fill a form:
 *  - numbered menus: the assistant asks one question at a time and saves after you confirm;
 *  - natural language (when GPT-4o is configured): describe what you need, the assistant asks for anything the form requires
 *    that you left out, then opens the real form with the values filled in. You review it and press Save yourself.
 */
export function ChatWidget() {
  const { user } = useAuth();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const { setPrefill } = usePrefill();
  const [open, setOpen] = useState(false);
  const [resp, setResp] = useState<Resp | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [aiEnabled, setAiEnabled] = useState(false);
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
    setAiEnabled(saved.ai);
  }, [userId]);
  useEffect(() => {
    if (userId == null) return;
    try {
      sessionStorage.setItem(storeKey(userId), JSON.stringify({ resp, lines: lines.slice(-60), ai: aiEnabled }));
    } catch {
      /* storage unavailable: the conversation just is not remembered */
    }
  }, [userId, resp, lines, aiEnabled]);
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
      const state = !fresh && resp && !isFill(resp) ? resp.state : null;
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
      if (next.stage === "menu" && typeof next.ai === "boolean") setAiEnabled(next.ai);
      setResp(next);
      setText("");
      setPicked([]);
    } catch (err) {
      fail(err, echo);
    } finally {
      setBusy(false);
    }
  }

  /** One turn of natural-language filling. */
  async function sendFill(input: string | null, echo?: string, start?: { form: string; target?: number }) {
    setBusy(true);
    try {
      const state = !start && isFill(resp) ? resp.state : null;
      const next = await api<FillResponse>("/api/assistant/fill", {
        body: { state, input, tz_offset: new Date().getTimezoneOffset(), form: start?.form ?? null, target: start?.target ?? null },
      });
      if (next.stage === "cancelled") {
        setLines((l) => [...l, ...(echo ? [{ from: "me" as const, text: echo }] : []), { from: "bot", text: next.message }]);
        setText("");
        await send(null, undefined, true);
        return;
      }
      const add: Line[] = [];
      if (echo) add.push({ from: "me", text: echo });
      if (next.notes.length) add.push({ from: "bot", text: `I could not use: ${next.notes.join("; ")}.`, error: true });
      if (next.error) add.push({ from: "bot", text: next.error, error: true });
      add.push({ from: "bot", text: next.message });
      setLines((l) => [...l, ...add]);
      setResp(next);
      setText("");
    } catch (err) {
      fail(err, echo);
    } finally {
      setBusy(false);
    }
  }

  function openForm(f: NonNullable<FillResponse["fill"]>) {
    setPrefill({ form: f.form, target: f.target, values: f.values });
    setLines((l) => [...l, { from: "bot", text: "I opened the form with your values filled in. Check them, then press Save yourself." }]);
    setOpen(false);
    router.push(f.route);
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

  const fillMode = isFill(resp);
  const menuMode = !fillMode && resp?.stage === "menu";
  const freeText = !fillMode && resp?.stage === "step" && resp.kind !== "choice" && resp.kind !== "multichoice" && resp.kind !== "file";
  const here = pageForm(pathname, user.role);

  function submitText(e: React.FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value) return;
    if (fillMode || menuMode) void sendFill(value, value);
    else void send(value, value);
  }
  const onEnter = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitText(e as unknown as React.FormEvent);
    }
  };
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
              {!fillMode && resp?.progress && resp.stage !== "menu" && (
                <div className="text-xs text-muted-foreground">Step {Math.min(resp.progress.done + 1, resp.progress.total)} of {resp.progress.total}</div>
              )}
              {fillMode && <div className="text-xs text-muted-foreground">Natural language - you review and save</div>}
            </div>
            <Button variant="ghost" size="sm" onClick={startOver} disabled={busy}>Start over</Button>
            <Button variant="ghost" size="icon" aria-label="Close chat assistant" onClick={() => setOpen(false)}>
              <X className="size-4" />
            </Button>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3 text-sm">
            {lines.slice(-30).map((l, i) => (
              <div key={i} className={l.from === "me" ? "flex justify-end" : "flex"}>
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
            ))}
            {!fillMode && resp?.stage === "summary" && resp.summary && (
              <div className="rounded-lg border p-3">
                {resp.summary.map((s) => (
                  <div key={s.label} className="flex justify-between gap-3 py-0.5">
                    <span className="text-muted-foreground">{s.label}</span>
                    <span className="text-right font-medium">{s.value}</span>
                  </div>
                ))}
              </div>
            )}
            {!fillMode && resp?.stage === "summary" && resp.warning && <p className="rounded-md bg-amber-500/15 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">{resp.warning}</p>}
            {fillMode && resp.values.length > 0 && (
              <div className="rounded-lg border border-violet-400/40 p-3">
                <div className="mb-1 flex items-center gap-1 text-xs font-medium text-violet-700 dark:text-violet-300">
                  <Sparkles className="size-3" /> Understood so far
                </div>
                {resp.values.map((v) => (
                  <div key={v.label} className="flex justify-between gap-3 py-0.5">
                    <span className="text-muted-foreground">{v.label}</span>
                    <span className="text-right font-medium">{v.value}</span>
                  </div>
                ))}
              </div>
            )}
            {!fillMode && resp?.hint && resp.stage === "step" && <p className="text-xs text-muted-foreground">{resp.hint}</p>}
            <div ref={bottom} />
          </div>

          <div className="space-y-2 border-t p-3">
            {/* ---- numbered menus */}
            {!fillMode && resp && (resp.kind === "choice" || resp.stage === "menu") && resp.options.length > 0 &&
              optionButtons(resp.options, resp.controls.more, (k, label) => void send(k, label), () => void send("9", "More"))}

            {!fillMode && resp?.kind === "multichoice" && (
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

            {!fillMode && resp?.kind === "file" && (
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

            {!fillMode && (freeText || resp?.kind === "choice") && (
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

            {!fillMode && resp && resp.stage !== "menu" && (
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

            {/* ---- natural language */}
            {menuMode && aiEnabled && (
              <div className="space-y-2">
                {here && (
                  <Button size="sm" variant="outline" disabled={busy} className="w-full" onClick={() => void sendFill(null, "Fill this page with AI", here)}>
                    <Sparkles className="mr-1 size-4" />
                    Fill this form with AI
                  </Button>
                )}
                <form onSubmit={submitText} className="space-y-2">
                  <Textarea aria-label="Describe what you need" rows={2} value={text} disabled={busy} onChange={(e) => setText(e.target.value)} onKeyDown={onEnter} placeholder="Or just describe what you need, for example: I need 50 laptops, open to all suppliers" />
                  <Button type="submit" size="sm" disabled={busy || !text.trim()}>
                    <Sparkles className="mr-1 size-4" />
                    Ask AI
                  </Button>
                </form>
              </div>
            )}

            {fillMode && (
              <div className="space-y-2">
                {resp.stage === "pick" && resp.options.length > 0 &&
                  optionButtons(resp.options, resp.controls.more, (k, label) => void sendFill(k, label), () => void sendFill("9", "More"))}
                {resp.stage === "ready" && resp.fill && (
                  <Button size="sm" className="w-full" disabled={busy} onClick={() => openForm(resp.fill!)}>
                    <ExternalLink className="mr-1 size-4" />
                    Open the form with these values
                  </Button>
                )}
                <form onSubmit={submitText} className="space-y-2">
                  {resp.stage === "pick" ? (
                    <div className="flex gap-2">
                      <Input aria-label="Your answer" value={text} disabled={busy} onChange={(e) => setText(e.target.value)} placeholder="Type to search, or describe what you need" />
                      <Button type="submit" size="icon" aria-label="Send" disabled={busy || !text.trim()}>
                        <Send className="size-4" />
                      </Button>
                    </div>
                  ) : (
                    <>
                      <Textarea
                        aria-label="Describe it in your own words"
                        rows={2}
                        value={text}
                        disabled={busy}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={onEnter}
                        placeholder={resp.stage === "ask" ? "Answer in your own words" : resp.stage === "ready" ? "Anything to change? Tell me" : "Describe it in your own words"}
                      />
                      <Button type="submit" size="sm" variant={resp.stage === "ready" ? "outline" : "default"} disabled={busy || !text.trim()}>
                        <Send className="mr-1 size-4" />
                        Send
                      </Button>
                    </>
                  )}
                </form>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void sendFill(resp.stage === "pick" ? "0" : "back", "Back")}>
                    <ChevronLeft className="mr-1 size-4" />
                    Back
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void sendFill("*", "Cancel")}>
                    Cancel
                  </Button>
                </div>
              </div>
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
