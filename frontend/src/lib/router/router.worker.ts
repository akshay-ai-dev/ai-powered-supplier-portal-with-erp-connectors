/// <reference lib="webworker" />
// Semantic router: embeds the buyer's question with all-MiniLM-L6-v2 (q8, WASM) and picks the closest
// route centroid. Runs in a worker so the page never blocks; the model is served from the portal
// (public/models) and cached by the browser after the first load.
import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";
import routes from "./routes.json";
import precomputed from "./centroids.json";

export const MODEL = "Xenova/all-MiniLM-L6-v2";
const TAU = 0.4; // minimum similarity for the top route
const DELTA = 0.05; // minimum lead over the runner-up

type Routes = Record<string, string[]>;
export type WorkerIn = { type: "init"; modelsUrl: string } | { type: "classify"; id: number; text: string };
export type WorkerOut =
  | { type: "ready"; ms: number; centroids: "file" | "computed" }
  | { type: "result"; id: number; tool: string; scores: Record<string, number> }
  | { type: "error"; id?: number; message: string };

let extractor: FeatureExtractionPipeline | null = null;
let centroids: Record<string, number[]> = {};

/** FNV-1a over the routes file, so stale centroids (routes edited, script not re-run) are detected. */
function routesHash(r: Routes): string {
  let h = 0x811c9dc5;
  for (const ch of JSON.stringify(r)) h = Math.imul(h ^ ch.charCodeAt(0), 0x01000193) >>> 0;
  return h.toString(16);
}

/** Drops request numbers before embedding: the router judges intent only (classify.ts extracts the number),
 * and "REQ2001" appearing in most utterances would pull the detail, compare and award routes together. */
export function stripRequestNumbers(text: string): string {
  return text
    .replace(/\bREQ[\s-]?#?\d+\b/gi, " ")
    .replace(/\brequest\s+#?\d{3,}\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalize(v: number[]): number[] {
  const norm = Math.hypot(...v) || 1;
  return v.map((x) => x / norm);
}

async function embed(texts: string[]): Promise<number[][]> {
  const out = await extractor!(texts.map(stripRequestNumbers), { pooling: "mean", normalize: true });
  return out.tolist() as number[][];
}

async function computeCentroids(): Promise<Record<string, number[]>> {
  const result: Record<string, number[]> = {};
  for (const [route, utterances] of Object.entries(routes as Routes)) {
    const vecs = await embed(utterances);
    const mean = vecs[0].map((_, i) => vecs.reduce((s, v) => s + v[i], 0) / vecs.length);
    result[route] = normalize(mean);
  }
  return result;
}

async function init(modelsUrl: string) {
  const t0 = performance.now();
  const base = modelsUrl.replace(/\/$/, "");
  // The models URL is our "remote host" (portal or file storage, never Hugging Face). Transformers.js 4.x skips
  // its tokenizer-file check when localModelPath is an absolute URL, so local-model mode would load no tokenizer.
  env.allowLocalModels = false;
  env.allowRemoteModels = true;
  env.remoteHost = `${base}/`;
  env.remotePathTemplate = "{model}/";
  env.backends.onnx.wasm!.wasmPaths = {
    mjs: `${base}/ort/transformers/ort-wasm-simd-threaded.asyncify.mjs`,
    wasm: `${base}/ort/transformers/ort-wasm-simd-threaded.asyncify.wasm`,
  };
  extractor = await pipeline("feature-extraction", MODEL, { dtype: "q8", device: "wasm" });

  const file = precomputed as { model?: string; routesHash?: string; centroids?: Record<string, number[]> };
  const fresh = file.model === MODEL && file.routesHash === routesHash(routes as Routes) && file.centroids;
  centroids = fresh ? file.centroids! : await computeCentroids();
  await embed(["warmup"]);
  return { ms: Math.round(performance.now() - t0), centroids: fresh ? ("file" as const) : ("computed" as const) };
}

async function classify(text: string) {
  const [q] = await embed([text]);
  const scores: Record<string, number> = {};
  for (const [route, c] of Object.entries(centroids)) scores[route] = q.reduce((s, x, i) => s + x * c[i], 0);
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const [top, best] = ranked[0];
  const second = ranked[1]?.[1] ?? -1;
  const tool = top !== "none" && best >= TAU && best - second >= DELTA ? top : "none";
  return { tool, scores };
}

const ctx = self as unknown as DedicatedWorkerGlobalScope;
let ready: Promise<unknown> | null = null;

ctx.onmessage = async (e: MessageEvent<WorkerIn>) => {
  const msg = e.data;
  if (msg.type === "init") {
    ready ??= init(msg.modelsUrl).then(
      (r) => ctx.postMessage({ type: "ready", ...r } satisfies WorkerOut),
      (err) => ctx.postMessage({ type: "error", message: String(err?.message ?? err) } satisfies WorkerOut),
    );
    return;
  }
  try {
    await ready;
    ctx.postMessage({ type: "result", id: msg.id, ...(await classify(msg.text)) } satisfies WorkerOut);
  } catch (err) {
    ctx.postMessage({ type: "error", id: msg.id, message: String((err as Error)?.message ?? err) } satisfies WorkerOut);
  }
};
