/// <reference lib="webworker" />
// Moonshine v2 Medium Streaming (English, int8) speech-to-text on ONNX Runtime Web (WASM), ported from
// experiments/moonshine_browser_stt/moonshine_wasm_stt.html. See docs/STT_API_REFERENCE.md §9.
// Input: mono 16 kHz Float32 PCM (decoded on the main thread; workers have no AudioContext).
import * as ort from "onnxruntime-web/wasm";

const SAMPLE_RATE = 16000;
const LAYERS = 14;
const HEADS = 10;
const HEAD_DIM = 64;
const BOS = 1;
const EOS = 2;
const FIRST_ADDED_TOKEN = 32000; // ids <= EOS and >= this are special tokens
const TOKENS_PER_SECOND = 6.5; // max decode length per second of audio (model card), stops hallucination loops
const MAX_SEGMENT_S = 30; // longer audio is split at the quietest point near this length
const ENCODER = "encoder_model_quantized.onnx";
const DECODER = "decoder_model_merged_quantized.onnx";

export type SttIn = { type: "init"; modelsUrl: string } | { type: "transcribe"; id: number; pcm: Float32Array };
export type SttOut =
  | { type: "ready"; ms: number; threads: number }
  | { type: "result"; id: number; text: string; ms: number }
  | { type: "error"; id?: number; message: string };

let encoder: ort.InferenceSession;
let decoder: ort.InferenceSession;
let vocab: string[] = [];

async function load(modelsUrl: string) {
  const t0 = performance.now();
  const base = modelsUrl.replace(/\/$/, "");
  const dir = `${base}/moonshine-streaming-medium/`;
  const threads = self.crossOriginIsolated ? Math.min(navigator.hardwareConcurrency || 4, 8) : 1;
  ort.env.wasm.wasmPaths = `${base}/ort/moonshine/`;
  ort.env.wasm.numThreads = threads;
  // External-data weights: ORT copies them into WASM memory once (tab footprint ~0.6 GB).
  const session = (file: string) =>
    ort.InferenceSession.create(dir + file, {
      executionProviders: ["wasm"],
      graphOptimizationLevel: "all",
      externalData: [{ path: `${file}.data`, data: `${dir}${file}.data` }],
    });
  // Sequential, so only one weights download buffer is alive at a time.
  encoder = await session(ENCODER);
  decoder = await session(DECODER);
  const tok = await (await fetch(dir + "tokenizer.json")).json();
  vocab = [];
  for (const [piece, id] of Object.entries(tok.model.vocab as Record<string, number>)) vocab[id] = piece;
  return { ms: Math.round(performance.now() - t0), threads };
}

function argmax(arr: ArrayLike<number>): number {
  let best = 0;
  for (let i = 1; i < arr.length; i++) if (arr[i] > arr[best]) best = i;
  return best;
}

// Split audio longer than maxS seconds at the quietest 50 ms window in the last 5 s of each piece.
function splitAtSilence(pcm: Float32Array, maxS: number): Float32Array[] {
  const max = maxS * SAMPLE_RATE;
  const search = 5 * SAMPLE_RATE;
  const win = 0.05 * SAMPLE_RATE;
  const segments: Float32Array[] = [];
  let start = 0;
  while (pcm.length - start > max) {
    let cut = start + max;
    let bestEnergy = Infinity;
    for (let s = start + max - search; s + win <= start + max; s += win) {
      let e = 0;
      for (let i = s; i < s + win; i++) e += pcm[i] * pcm[i];
      if (e < bestEnergy) {
        bestEnergy = e;
        cut = s + win / 2;
      }
    }
    segments.push(pcm.subarray(start, cut));
    start = cut;
  }
  segments.push(pcm.subarray(start));
  return segments;
}

// SentencePiece-style BPE: "▁" = space, <0xNN> = byte fallback, strip one leading space.
function detokenize(ids: number[]): string {
  const utf8 = new TextDecoder();
  let out = "";
  let bytes: number[] = [];
  const flush = () => {
    if (bytes.length) {
      out += utf8.decode(new Uint8Array(bytes));
      bytes = [];
    }
  };
  for (const id of ids) {
    if (id <= EOS || id >= FIRST_ADDED_TOKEN) continue;
    const piece = vocab[id];
    const byte = /^<0x([0-9A-Fa-f]{2})>$/.exec(piece);
    if (byte) {
      bytes.push(parseInt(byte[1], 16));
      continue;
    }
    flush();
    out += piece.replaceAll("▁", " ");
  }
  flush();
  return (out.startsWith(" ") ? out.slice(1) : out).trim();
}

// Encoder: raw audio padded to a multiple of 80 samples -> [1, T, 768] at 50 Hz. Decoder: one graph gated by
// use_cache_branch; step 0 returns the cross-attention cache, reused for every later step.
async function transcribeSegment(pcm: Float32Array): Promise<string> {
  const n = pcm.length;
  const padded = Math.ceil(n / 80) * 80;
  const audio = new Float32Array(padded);
  audio.set(pcm);
  const mask = new BigInt64Array(padded);
  mask.fill(BigInt(1), 0, n); // BigInt() not 1n: tsconfig targets ES2017
  const { encoder_hidden_states: hidden } = await encoder.run({
    input_values: new ort.Tensor("float32", audio, [1, padded]),
    attention_mask: new ort.Tensor("int64", mask, [1, padded]),
  });

  const empty = new ort.Tensor("float32", new Float32Array(0), [1, HEADS, 0, HEAD_DIM]);
  const past: Record<string, ort.Tensor> = {};
  for (let i = 0; i < LAYERS; i++) {
    for (const kind of ["decoder", "encoder"]) {
      for (const kv of ["key", "value"]) past[`past_key_values.${i}.${kind}.${kv}`] = empty;
    }
  }

  const ids: number[] = [];
  let token = BOS;
  const maxSteps = Math.max(1, Math.ceil((n / SAMPLE_RATE) * TOKENS_PER_SECOND));
  for (let step = 0; step < maxSteps; step++) {
    const out = await decoder.run({
      input_ids: new ort.Tensor("int64", BigInt64Array.of(BigInt(token)), [1, 1]),
      encoder_hidden_states: hidden,
      use_cache_branch: new ort.Tensor("bool", Uint8Array.of(step > 0 ? 1 : 0), [1]),
      ...past,
    });
    token = argmax(out.logits.data as Float32Array);
    for (let i = 0; i < LAYERS; i++) {
      for (const kv of ["key", "value"]) {
        past[`past_key_values.${i}.decoder.${kv}`] = out[`present.${i}.decoder.${kv}`];
        if (step === 0) past[`past_key_values.${i}.encoder.${kv}`] = out[`present.${i}.encoder.${kv}`];
      }
    }
    if (token === EOS) break;
    ids.push(token);
  }
  return detokenize(ids);
}

async function transcribe(pcm: Float32Array): Promise<string> {
  const texts: string[] = [];
  for (const segment of splitAtSilence(pcm, MAX_SEGMENT_S)) {
    const text = await transcribeSegment(segment);
    if (text) texts.push(text);
  }
  return texts.join(" ");
}

const ctx = self as unknown as DedicatedWorkerGlobalScope;
let ready: Promise<unknown> | null = null;

ctx.onmessage = async (e: MessageEvent<SttIn>) => {
  const msg = e.data;
  if (msg.type === "init") {
    ready ??= load(msg.modelsUrl).then(
      (r) => ctx.postMessage({ type: "ready", ...r } satisfies SttOut),
      (err) => ctx.postMessage({ type: "error", message: String(err?.message ?? err) } satisfies SttOut),
    );
    return;
  }
  try {
    await ready;
    const t0 = performance.now();
    const text = await transcribe(msg.pcm);
    ctx.postMessage({ type: "result", id: msg.id, text, ms: Math.round(performance.now() - t0) } satisfies SttOut);
  } catch (err) {
    ctx.postMessage({ type: "error", id: msg.id, message: String((err as Error)?.message ?? err) } satisfies SttOut);
  }
};
