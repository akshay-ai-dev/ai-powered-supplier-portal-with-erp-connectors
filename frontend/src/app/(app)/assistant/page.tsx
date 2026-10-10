"use client";
// Buyer Assistant: a full-page chat for buyers (and admins). Each question goes to POST /api/assistant/chat, where
// GPT-4o picks one of the buyer's 10 MCP tools; the answer is that tool's result as is (answer-templates.tsx).
// Drafts are saved only when the buyer confirms the card. The floating chat widget is hidden on this page.
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ChatReply } from "@/lib/types";
import { AnswerView, ErrorAnswer } from "@/components/assistant/answer-templates";
import { stampDraft } from "@/components/assistant/confirm-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Line = { from: "me"; text: string } | { from: "answer"; reply: ChatReply } | { from: "error"; text: string };
type Turn = { role: "user"; content: string } | { role: "assistant"; tool: string; args: Record<string, unknown> };

/** One starter per buyer tool. A click puts the text in the box to edit (the numbers are examples), Enter sends it. */
const STARTERS = [
  { title: "Waiting for an award", text: "Which requests are waiting for an award?" },
  { title: "Request details", text: "Show REQ2002" },
  { title: "Compare responses", text: "Compare the responses for REQ2001" },
  { title: "ERP documents", text: "Show the ERP documents for REQ2001" },
  { title: "Find a supplier", text: "Find supplier Globex" },
  { title: "Check stock", text: "How much ITEM001 do we have?" },
  { title: "New request", text: "I need 40 boxes of ITEM008 by 2026-11-30 through Infor" },
  { title: "Award a supplier", text: "Award REQ2001 to the top-ranked supplier" },
  { title: "Approve a purchase order", text: "Approve PO1001" },
  { title: "Draft a purchase order", text: "Order 5 ITEM001 from supplier 2" },
];
const HISTORY = 10; // earlier turns sent with a question
const storeKey = (id: number) => `erp_buyer_assistant_${id}`;

/** What GPT-4o sees: earlier questions and the tools called with their arguments, never tool results. */
function chatHistory(lines: Line[]): Turn[] {
  const turns = lines.flatMap((l): Turn[] => {
    if (l.from === "me") return [{ role: "user", content: l.text }];
    if (l.from === "answer" && l.reply.tool) return [{ role: "assistant", tool: l.reply.tool, args: l.reply.args ?? {} }];
    return [];
  });
  return turns.slice(-HISTORY);
}

export default function BuyerAssistantPage() {
  const { user } = useAuth();
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [restored, setRestored] = useState(false); // never save before the saved conversation is back
  const userId = user?.id;

  useEffect(() => {
    if (userId == null) return;
    try {
      const raw = sessionStorage.getItem(storeKey(userId));
      if (raw) setLines(JSON.parse(raw) as Line[]);
    } catch {
      /* private mode or corrupt value: start fresh */
    }
    setRestored(true);
  }, [userId]);
  useEffect(() => {
    if (userId == null || !restored) return;
    try {
      sessionStorage.setItem(storeKey(userId), JSON.stringify(lines.slice(-60)));
    } catch {
      /* storage unavailable: the conversation just is not remembered */
    }
  }, [userId, restored, lines]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [lines, busy]);

  if (!user) return null;
  if (user.role !== "buyer" && user.role !== "admin")
    return <p className="text-muted-foreground">The Buyer Assistant is for buyers. Use the chat button on the other pages.</p>;

  async function ask(question: string) {
    setBusy(true);
    setText("");
    const history = chatHistory(lines);
    setLines((l) => [...l, { from: "me", text: question }]);
    try {
      const reply = stampDraft(await api<ChatReply>("/api/assistant/chat", { body: { message: question, history, tz_offset: new Date().getTimezoneOffset() } }));
      setLines((l) => [...l, { from: "answer", reply }]);
    } catch (err) {
      setLines((l) => [...l, { from: "error", text: err instanceof Error ? err.message : "Something went wrong" }]);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => input.current?.focus());
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = text.trim();
    if (q && !busy) void ask(q);
  }

  function pickStarter(t: string) {
    setText(t);
    requestAnimationFrame(() => {
      input.current?.focus();
      input.current?.setSelectionRange(t.length, t.length);
    });
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-9rem)] w-full max-w-3xl flex-col">
      <div className="flex-1 space-y-4 pb-4 text-sm">
        {lines.length === 0 ? (
          <div className="pt-6 text-center md:pt-12">
            <Sparkles className="mx-auto size-8 text-muted-foreground" />
            <h1 className="mt-3 text-2xl font-semibold">Buyer Assistant</h1>
            <p className="mx-auto mt-2 max-w-xl text-muted-foreground">
              Ask about your requests, quotes, suppliers, stock and ERP documents, or have it draft a request, an award or a purchase order.
              Nothing is saved until you confirm.
            </p>
            <div className="mt-8 grid gap-2 text-left sm:grid-cols-2">
              {STARTERS.map((s) => (
                <button key={s.title} type="button" onClick={() => pickStarter(s.text)} className="rounded-lg border p-3 text-left transition-colors hover:bg-accent/50">
                  <div className="font-medium">{s.title}</div>
                  <div className="mt-0.5 text-muted-foreground">{s.text}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          lines.map((l, i) =>
            l.from === "me" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2 text-primary-foreground">{l.text}</div>
              </div>
            ) : l.from === "error" ? (
              <ErrorAnswer key={i} message={l.text} />
            ) : (
              <div key={i} className="space-y-1">
                {l.reply.tool && <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">used: {l.reply.tool}</span>}
                {l.reply.tool === null ? (
                  <div className="space-y-1">
                    <p>I could not match that to something I can look up or draft. Try for example:</p>
                    <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                      {(l.reply.help ?? []).map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <AnswerView reply={l.reply} />
                )}
              </div>
            ),
          )
        )}
        {busy && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
        <div ref={bottom} />
      </div>

      <form onSubmit={submit} className="sticky bottom-0 flex items-center gap-2 border-t bg-background py-3">
        {lines.length > 0 && (
          <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setLines([])}>
            New chat
          </Button>
        )}
        <Input
          ref={input}
          aria-label="Ask the Buyer Assistant"
          className="h-11 flex-1 rounded-full px-4"
          value={text}
          disabled={busy}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask about requests, quotes, suppliers, stock or POs…"
        />
        <Button type="submit" size="icon" aria-label="Send" className="size-11 shrink-0 rounded-full" disabled={busy || !text.trim()}>
          <ArrowUp className="size-5" />
        </Button>
      </form>
    </div>
  );
}
