// Client side of the semantic router: owns the worker, and pulls the request number and stages out
// of the question (the router only picks the tool; it never extracts parameters).
import type { WorkerIn, WorkerOut } from "./router.worker";

export type Tool = "list_requests" | "get_request_detail" | "compare_responses" | "draft_award";
export type Route = Tool | "none";
export interface RouteResult {
  tool: Route;
  scores: Record<string, number>;
}

/** Where the browser loads models from; point it at file storage later without code changes. */
export const MODELS_URL = process.env.NEXT_PUBLIC_MODELS_URL || "/models";

/** "REQ2001", "req 2001", "REQ-2001" or "request 2001" -> "REQ2001". */
export function extractReqNumber(text: string): string | null {
  const m = /\bREQ[\s-]?#?(\d+)\b/i.exec(text) ?? /\brequest\s+#?(\d{3,})\b/i.exec(text);
  return m ? `REQ${m[1]}` : null;
}

// First match wins, so more specific phrases come first.
const STAGE_PATTERNS: [RegExp, string[]][] = [
  [/\b(waiting (for|on) (an )?award|awaiting (an )?award|need(s)? (an )?award|to award)\b/i, ["Quoted", "Quotes closed"]],
  [/\b(quotes closed|past (the |their )?deadline|deadline (passed|reached))\b/i, ["Quotes closed"]],
  [/\bin transit\b/i, ["In Transit"]],
  [/\bdelivered\b/i, ["Delivered"]],
  [/\brejected\b/i, ["Rejected"]],
  [/\bcancel+ed\b/i, ["Cancelled"]],
  [/\bawarded\b/i, ["Awarded"]],
  [/\b(quoted|got quotes|with quotes)\b/i, ["Quoted"]],
  [/\b(no (bids|quotes|responses)|without (bids|quotes|responses))\b/i, ["Open"]],
  [/\bopen\b/i, ["Open", "Quoted", "Quotes closed"]],
  [/\bclosed\b/i, ["Closed"]],
];

/** Stages a list question asks about, e.g. "in transit" -> ["In Transit"]; [] means all. */
export function extractStages(text: string): string[] {
  return STAGE_PATTERNS.find(([re]) => re.test(text))?.[1] ?? [];
}

export class SemanticRouter {
  private worker: Worker;
  private nextId = 0;
  private pending = new Map<number, { resolve: (r: RouteResult) => void; reject: (e: Error) => void }>();
  readonly ready: Promise<{ ms: number; centroids: "file" | "computed" }>;

  constructor() {
    this.worker = new Worker(new URL("./router.worker.ts", import.meta.url), { type: "module" });
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = (e: MessageEvent<WorkerOut>) => {
        const msg = e.data;
        if (msg.type === "ready") return resolve(msg);
        const waiter = msg.id !== undefined ? this.pending.get(msg.id) : undefined;
        if (msg.type === "error" && !waiter) return reject(new Error(msg.message));
        if (!waiter || msg.id === undefined) return;
        this.pending.delete(msg.id);
        if (msg.type === "result") waiter.resolve({ tool: msg.tool as Route, scores: msg.scores });
        else waiter.reject(new Error(msg.message));
      };
    });
    const absolute = new URL(MODELS_URL, location.origin).href;
    this.worker.postMessage({ type: "init", modelsUrl: absolute } satisfies WorkerIn);
  }

  classify(text: string): Promise<RouteResult> {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ type: "classify", id, text } satisfies WorkerIn);
    });
  }

  dispose() {
    this.worker.terminate();
  }
}
