"use client";
// Buyer AI Assistant (SRS §3.2, §6). A browser-side semantic router picks one of four MCP tools, the page calls
// that tool's REST copy (POST /api/mcp/<tool>) with the buyer's login, and shows the result in a fixed template.
// No LLM writes the answers.
import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Send, Square } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { extractReqNumber, extractStages, SemanticRouter, type Route } from "@/lib/router/classify";
import { useVoiceInput } from "@/lib/stt/use-voice-input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorNote, PageHeader } from "@/components/page-header";
import {
  ComparisonAnswer,
  ErrorAnswer,
  HelpAnswer,
  MissingRequestAnswer,
  RequestDetailAnswer,
  RequestsAnswer,
  type Comparison,
  type RequestDetail,
  type RequestRow,
} from "@/components/assistant/answer-templates";
import { DraftAwardCard, type DraftAward } from "@/components/assistant/draft-award-card";
import { VoiceWaveform } from "@/components/assistant/voice-waveform";

const EXAMPLES = ["Which requests are waiting for an award?", "Compare the responses for REQ2001", "Award REQ2001 to the top-ranked supplier"];

type Answer =
  | { kind: "list_requests"; data: RequestRow[]; stages: string[] }
  | { kind: "get_request_detail"; data: RequestDetail }
  | { kind: "compare_responses"; data: Comparison }
  | { kind: "draft_award"; data: DraftAward }
  | { kind: "help" }
  | { kind: "missing" }
  | { kind: "error"; message: string };

type Entry = { id: number; question: string; tool?: Route; scores?: Record<string, number>; answer?: Answer };

function AnswerView({ answer }: { answer: Answer }) {
  switch (answer.kind) {
    case "list_requests":
      return <RequestsAnswer rows={answer.data} stages={answer.stages} />;
    case "get_request_detail":
      return <RequestDetailAnswer data={answer.data} />;
    case "compare_responses":
      return <ComparisonAnswer data={answer.data} />;
    case "draft_award":
      return <DraftAwardCard draft={answer.data} />;
    case "help":
      return <HelpAnswer />;
    case "missing":
      return <MissingRequestAnswer />;
    case "error":
      return <ErrorAnswer message={answer.message} />;
  }
}

async function answerFor(text: string, tool: Route): Promise<Answer> {
  if (tool === "none") return { kind: "help" };
  if (tool === "list_requests") return { kind: tool, data: await api<RequestRow[]>("/api/mcp/list_requests", { body: {} }), stages: extractStages(text) };
  const req_number = extractReqNumber(text);
  if (!req_number) return { kind: "missing" };
  const data = await api(`/api/mcp/${tool}`, { body: { req_number } });
  return { kind: tool, data } as Answer;
}

export default function AssistantPage() {
  const { user } = useAuth();
  const router = useRef<SemanticRouter | null>(null);
  const [routerState, setRouterState] = useState<"loading" | "ready" | "error">("loading");
  const [routerError, setRouterError] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const voice = useVoiceInput((text) => setDraft(text));

  useEffect(() => {
    const r = new SemanticRouter();
    router.current = r;
    r.ready.then(
      () => setRouterState("ready"),
      (e: Error) => {
        setRouterError(e.message);
        setRouterState("error");
      },
    );
    return () => r.dispose();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [entries]);

  if (user && user.role !== "buyer") return <ErrorNote message="The AI Assistant is available to buyers only." />;

  async function ask(question: string) {
    const text = question.trim();
    if (!text || !router.current || busy) return;
    const id = Date.now();
    setDraft("");
    setBusy(true);
    setEntries((e) => [...e, { id, question: text }]);
    const update = (patch: Partial<Entry>) => setEntries((e) => e.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    try {
      const { tool, scores } = await router.current.classify(text);
      if (process.env.NODE_ENV !== "production") console.debug("router", { text, tool, scores });
      update({ tool, scores });
      update({ answer: await answerFor(text, tool) });
    } catch (e) {
      update({ answer: { kind: "error", message: e instanceof Error ? e.message : "Something went wrong" } });
    } finally {
      setBusy(false);
    }
  }

  const voiceLabel = { idle: "Speak", loading: "Loading voice model…", recording: "Stop and transcribe", transcribing: "Transcribing…" }[voice.state];
  const voiceStatus = voice.state === "recording" ? "Listening… click ■ to stop" : voiceLabel;

  return (
    <>
      <PageHeader title="AI Assistant" description="Ask about your requests. Drafts are never saved until you confirm." />
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="min-h-64 space-y-6" aria-live="polite">
            {entries.length === 0 && (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">Try:</p>
                <div className="flex flex-wrap gap-2">
                  {EXAMPLES.map((q) => (
                    <Button key={q} variant="outline" size="sm" onClick={() => ask(q)} disabled={routerState !== "ready" || busy}>
                      {q}
                    </Button>
                  ))}
                </div>
              </div>
            )}
            {entries.map((e) => (
              <div key={e.id} className="space-y-2">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{e.question}</div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Assistant</span>
                    {e.tool && e.tool !== "none" && <span className="rounded bg-muted px-1.5 py-0.5 font-mono">used: {e.tool}</span>}
                    {e.scores && (
                      <details className="inline">
                        <summary className="cursor-pointer">routing</summary>
                        <span className="font-mono">
                          {Object.entries(e.scores)
                            .sort((a, b) => b[1] - a[1])
                            .map(([k, v]) => `${k} ${v.toFixed(2)}`)
                            .join(" · ")}
                        </span>
                      </details>
                    )}
                  </div>
                  {e.answer ? <AnswerView answer={e.answer} /> : <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <form
            className="flex items-center gap-2 border-t pt-4"
            onSubmit={(ev) => {
              ev.preventDefault();
              ask(draft);
            }}
          >
            {voice.state === "recording" && voice.analyser ? (
              <VoiceWaveform analyser={voice.analyser} />
            ) : (
              <Input
                aria-label="Question"
                value={draft}
                onChange={(ev) => setDraft(ev.target.value)}
                placeholder={routerState === "ready" ? "Ask about requests, quotes or awards…" : "Loading assistant…"}
                maxLength={500}
              />
            )}
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={voiceLabel}
              title={voiceLabel}
              onClick={voice.toggle}
              disabled={voice.state === "loading" || voice.state === "transcribing"}
            >
              {voice.state === "recording" ? <Square className="size-4" /> : voice.state === "idle" ? <Mic className="size-4" /> : <Loader2 className="size-4 animate-spin" />}
            </Button>
            <Button type="submit" disabled={routerState !== "ready" || busy || !draft.trim()}>
              <Send className="mr-1 size-4" />
              Send
            </Button>
          </form>
          {(voice.state !== "idle" || voice.error || routerState === "error") && (
            <p className={`text-xs ${voice.error || routerState === "error" ? "text-destructive" : "text-muted-foreground"}`}>
              {routerState === "error" ? `The assistant model failed to load: ${routerError}` : voice.error ?? `${voiceStatus}${voice.state === "loading" ? " (first time only, ~385 MB)" : ""}`}
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
