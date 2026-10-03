# STT API Reference — Parakeet TDT 0.6B in the browser (parakeet.js + ONNX Runtime Web WASM)

Browser-only speech-to-text: NVIDIA Parakeet TDT 0.6B as an **int8 ONNX** build, run with **parakeet.js** on **ONNX Runtime Web's WASM (CPU)** execution provider. Audio never leaves the device; there is no server inference.

Working proof: [`experiments/parakeet_browser_stt/parakeet_wasm_stt.html`](../experiments/parakeet_browser_stt/parakeet_wasm_stt.html) (screenshot: [`proof_v3_wasm_int8.png`](../experiments/parakeet_browser_stt/proof_v3_wasm_int8.png)).

Gathered 2026-10-02 from the published npm package source (`parakeet.js@1.4.4`: `src/*.js`, `types/*.d.ts`, README), the Hugging Face model repos (file listings via HF API), ONNX Runtime Web docs, and the upstream demo (`examples/demo/src/App.jsx`). Context7 has no index for parakeet.js (only the unrelated Rust `parakeet-rs`), so the package source is the primary reference.

---

## 1. Pinned versions

| Component | Version | Notes |
| --- | --- | --- |
| `parakeet.js` | **1.4.4** | ESM, MIT. Only dependency: `onnxruntime-web` (exact pin below). |
| `onnxruntime-web` | **1.24.1** | The version parakeet.js 1.4.4 pins. JS bundle and `.wasm` binaries **must** come from the same build. |
| Model v3 (multilingual) | `ysdede/parakeet-tdt-0.6b-v3-onnx` | 25 European languages, vocabulary 4097, 128 mel bins. CC-BY-4.0. |
| Model v2 (English) | `ysdede/parakeet-tdt-0.6b-v2-onnx` | English only, vocabulary 1025, 128 mel bins. CC-BY-4.0. |

## 2. Model files (int8 build)

Files fetched by `fromHub(key, { backend: 'wasm', encoderQuant: 'int8', decoderQuant: 'int8', preprocessorBackend: 'js' })`:

| File | v3 size | v2 size | Purpose |
| --- | --- | --- | --- |
| `encoder-model.int8.onnx` | 652.2 MB | 652.2 MB | FastConformer encoder |
| `decoder_joint-model.int8.onnx` | 18.2 MB | 9.0 MB | TDT prediction and joint network |
| `vocab.txt` | ~0.1 MB | ~0.03 MB | SentencePiece vocabulary |
| `nemo128.onnx` | 0.1 MB | 0.1 MB | Mel preprocessor. **Not downloaded** when `preprocessorBackend: 'js'` (default). |

Other variants in each repo: fp32 (`encoder-model.onnx` + 2.4 GB `.data`) and fp16 (1.24 GB encoder). For WASM, int8 is the right choice. fp32 is too large for comfortable browser memory, and fp16 is only meaningful on WebGPU.

**Download URL pattern:** `https://huggingface.co/{repoId}/resolve/main/{file}`. These URLs send `Access-Control-Allow-Origin: *`, so they work cross-origin and under COEP.

**Caching:** `fromHub` stores every downloaded file as a Blob in IndexedDB (`parakeet-cache-db` / store `file-store`, key `hf-{repoId}-{revision}-{subfolder}-{filename}`) and hands ORT a `blob:` URL. The cache is per origin, so each origin (including each localhost port) downloads its own ~670 MB copy. To clear it, run `indexedDB.deleteDatabase('parakeet-cache-db')`.

## 3. Loading — public API

```js
import { fromHub, fromUrls } from 'parakeet.js';
```

### `fromHub(repoIdOrModelKey, options) → Promise<ParakeetModel>`

`repoIdOrModelKey` is either `'parakeet-tdt-0.6b-v3'` / `'parakeet-tdt-0.6b-v2'` (keys in `MODELS`) or a full HF repo ID.

| Option | Type | Default | Notes |
| --- | --- | --- | --- |
| `backend` | `'webgpu' \| 'webgpu-hybrid' \| 'webgpu-strict' \| 'wasm'` | `'webgpu'` in hub, `'webgpu-hybrid'` in `fromUrls` | **Use `'wasm'`**: both encoder and decoder run on the WASM EP. |
| `encoderQuant` | `'int8' \| 'fp32' \| 'fp16'` | `'int8'` | ⚠ If `backend` starts with `webgpu`, int8 is **silently forced to fp32** (the 2.4 GB download). It stays int8 only with `backend: 'wasm'`. |
| `decoderQuant` | `'int8' \| 'fp32' \| 'fp16'` | `'int8'` | |
| `preprocessorBackend` | `'js' \| 'onnx'` | `'js'` | `js` = pure-JS mel spectrogram (`mel.js`); skips the `nemo128.onnx` download. |
| `preprocessor` | `'nemo80' \| 'nemo128'` | from model config (`nemo128`) | Only matters with `preprocessorBackend: 'onnx'`. |
| `cpuThreads` | `number` | `navigator.hardwareConcurrency` | Sets `ort.env.wasm.numThreads`. Forced to 1 when `SharedArrayBuffer` is unavailable. |
| `wasmPaths` | `string` | jsDelivr URL for the detected ORT version | Prefix for the ORT `.wasm` files. Only set when `ort.env.wasm.wasmPaths` is not already set. |
| `progress` | `({loaded, total, file}) => void` | — | Download progress for each file. Not called on cache hits. |
| `revision` | `string` | `'main'` | HF git revision. |
| `verbose` | `boolean` | `false` | ORT `logSeverityLevel` 0 instead of 2. |
| `enableProfiling` | `boolean` | `false` | ORT session profiling. |

Quantization is strict: a missing fp16 file throws an error instead of falling back.

### `fromUrls(cfg) → Promise<ParakeetModel>` (self-hosted assets)

Use this when serving the ONNX files from your own CDN or bucket, for example to avoid the HF dependency in production.

```js
const model = await fromUrls({
  encoderUrl:   '/models/parakeet-v3/encoder-model.int8.onnx',
  decoderUrl:   '/models/parakeet-v3/decoder_joint-model.int8.onnx',
  tokenizerUrl: '/models/parakeet-v3/vocab.txt',
  backend: 'wasm',
  preprocessorBackend: 'js',
  cpuThreads: 8,
  // wasmPaths: '/ort/',                 // self-host ORT binaries too
  // encoderDataUrl / decoderDataUrl:    // only for fp32 external-data builds
  // filenames: { encoder, decoder },    // required alongside *DataUrl
});
```

Other `FromUrlsConfig` fields: `preprocessorUrl` (required only for `preprocessorBackend: 'onnx'`), `subsampling` (8), `windowStride` (0.01 s), `nMels` (128), `enableGraphCapture` (WebGPU-strict only).

Session options used internally for `backend: 'wasm'`: `executionProviders: ['wasm']`, `graphOptimizationLevel: 'all'`, `executionMode: 'parallel'`, `enableCpuMemArena: true`, `enableMemPattern: true`. Encoder and decoder sessions are created in parallel.

## 4. Inference — `ParakeetModel`

All inference methods take **mono `Float32Array` PCM**, normally at 16 kHz.

### `transcribe(audio, sampleRate = 16000, opts) → Promise<TranscribeResult>`

Best for clips up to about a minute, or when the app owns the chunking.

| Option | Default | Effect |
| --- | --- | --- |
| `returnTimestamps` | `false` | Fills `words[]` / `tokens[]` with `start_time` / `end_time` (s). Without it, `words` is `[]`. |
| `returnConfidences` | `false` | Adds per-token and per-word `confidence` and detailed `confidence_scores`. |
| `temperature` | `1.0` | 1.0 = greedy. |
| `enableProfiling` | `true` | Populates `metrics`. |
| `timeOffset` | `0` | Seconds added to timestamps (for chunks of a larger stream). |
| `previousDecoderState` / `returnDecoderState` | `null` / `false` | Carry decoder state across chunks. |
| `prefixSamples`, `incremental: { cacheKey, prefixSeconds }` | — | Mel and encoder cache reuse for overlapping streaming windows. |
| `precomputedFeatures` | `null` | Skip the preprocessor (`{ features, T, melBins }`). |
| `returnTokenIds`, `returnFrameIndices`, `returnLogProbs`, `returnTdtSteps` | `false` | Alignment and debug arrays. |
| `frameStride`, `skipCMVN`, `debug` | `1`, `false`, `false` | Advanced. |

```ts
type TranscribeResult = {
  utterance_text: string;
  words: { text: string; start_time: number; end_time: number; confidence?: number }[];
  tokens?: { token: string; raw_token?: string; is_word_start?: boolean; start_time?: number; end_time?: number; confidence?: number }[];
  confidence_scores?: { token; token_avg; word; word_avg; frame; frame_avg; overall_log_prob };
  metrics?: { preprocess_ms; encode_ms; decode_ms; tokenize_ms; total_ms; rtf; mel_cache? } | null;
  is_final: boolean;
  decoderState?: { s1: Float32Array; s2: Float32Array; dims1: number[]; dims2: number[] };
  tokenIds?: number[]; frameIndices?: number[]; logProbs?: number[]; tdtSteps?: number[];
};
```

`metrics.rtf` is **audio seconds ÷ processing seconds**, so higher is faster (5.4 means 5.4× faster than real time).

### `transcribeLongAudio(audio, sampleRate, opts) → Promise<{ text, words?, chunks?, metrics? }>`

Built-in sentence-aware windowing for long recordings such as calls and meetings. Its options are `returnTimestamps` (`true` gives sentence chunks, `'word'` gives word chunks), `chunkLengthS` (0 = automatic), `timeOffset`, plus any `transcribe` option. Short inputs fall back to a single `transcribe` call. `chunks` is `{ text, timestamp: [start, end] }[]`.

### `createStreamingTranscriber(opts) → StatefulStreamingTranscriber`

For contiguous real-time chunks, such as a mic feed:

- `processChunk(Float32Array)` returns `{ chunkText, text, words, totalDuration, chunkCount, is_final, … }`.
- `finalize()` returns the final `{ text, words, … }`.
- `reset()` clears the state, and `getState()` reports it.

Its options are `returnTimestamps`, `returnConfidences`, `returnTokenIds`, `sampleRate`, and `debug`. The upstream demo feeds 30 s chunks for files longer than about 150 s. Keet ([repo](https://github.com/ysdede/keet)) is the reference real-time app.

### Other model methods and exports

- Model methods: `computeFeatures(audio, sr)`, `getStreamingConstants()` (`frameTimeStride` = 0.08 s), `frameToTime(i)`, `resetMelCache()`, `clearIncrementalCache()`, `setPreprocessorBackend('js'|'onnx')`.
- Package exports: `MODELS`, `LANGUAGE_NAMES`, `listModels()`, `supportsLanguage(key, lang)`, `getParakeetModel()` (download only, returns blob URLs), `getModelFile()`, `JsPreprocessor`, `FrameAlignedMerger`, `LCSPTFAMerger`.

## 5. Audio input (browser)

Parakeet expects mono 16 kHz Float32 PCM. Let Web Audio do the decoding and resampling:

```js
async function toMono16k(arrayBuffer) {
  const ctx = new AudioContext({ sampleRate: 16000 });     // resamples during decode
  const buf = await ctx.decodeAudioData(arrayBuffer);     // wav/mp3/ogg/webm/m4a…
  ctx.close();
  if (buf.numberOfChannels === 1) return buf.getChannelData(0);
  const mono = new Float32Array(buf.length);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const ch = buf.getChannelData(c);
    for (let i = 0; i < ch.length; i++) mono[i] += ch[i] / buf.numberOfChannels;
  }
  return mono;
}
```

The same function handles mic input: record with `MediaRecorder`, build a `Blob` from the chunks, then decode its `arrayBuffer()`.

## 6. ONNX Runtime Web WASM — what matters

| Setting | Meaning |
| --- | --- |
| `ort.env.wasm.wasmPaths` | Prefix or map for the `.wasm` binaries. Must match the ORT JS version exactly (`https://cdn.jsdelivr.net/npm/onnxruntime-web@1.24.1/dist/`). |
| `ort.env.wasm.numThreads` | 0 = automatic (min(4, cores/2)). parakeet.js sets it to `cpuThreads`. >1 needs `crossOriginIsolated`. |
| `ort.env.wasm.proxy` | Runs inference in a Web Worker. parakeet.js sets `false`, so inference runs on the calling thread. For production UI, put the whole model in your own Worker (§8). |
| Import path | `onnxruntime-web/wasm` (`dist/ort.wasm.min.mjs`) is the WASM-only bundle, smaller than the default that includes WebGPU. parakeet.js does `import('onnxruntime-web')`, so map that specifier to the WASM bundle (import map, or a bundler alias). |

**Multi-threading needs cross-origin isolation.** `SharedArrayBuffer` exists only when `self.crossOriginIsolated === true`, which requires the page to be served with:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp      (or: credentialless)
```

With these headers, every cross-origin subresource must be CORS-enabled or send `Cross-Origin-Resource-Policy: cross-origin`. jsDelivr (ORT, parakeet.js) and huggingface.co (models, samples) both qualify. Without isolation, inference still works on one thread, about 4× slower (see §7).

Vite dev server equivalent:

```js
// vite.config.js
server: { headers: { 'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp' } }
```

Use the same headers for production hosting (`vercel.json` headers, nginx `add_header`, and so on). COOP `same-origin` breaks `window.opener` popups such as OAuth popup flows on that page. Scope the headers to the routes that need STT, or use COEP `credentialless`.

## 7. Measured results (proof run)

Machine: Apple M5, 10 cores, Chrome. Clip: `jfk.wav` (11.0 s, from `huggingface.co/datasets/Xenova/transformers.js-docs`). Each run was checked against the known transcript after removing punctuation and case.

| Model | Threads | Load (download + session) | Transcribe 11 s | Speed | Encode / decode | Result |
| --- | --- | --- | --- | --- | --- | --- |
| v3 int8 | 8 (COOP/COEP) | 13.7 s (cold download) | 2.02 s | 5.4× RT | 1937 / 76 ms | PASS |
| v2 int8 | 8 (COOP/COEP) | 14.3 s (cold download) | 1.82 s | 6.0× RT | 1777 / 38 ms | PASS |
| v3 int8 | 1 (no isolation) | 13.2 s (cold download) | 7.94 s | 1.4× RT | 7672 / 247 ms | PASS |

- v3 output: "And so, my fellow Americans, ask not what your country can do for you. Ask what you can do for your country."
- v2 output: the same sentence, but with a comma where v3 puts a period.
- The encoder dominates the cost, roughly 95% of the time. The JS preprocessor takes about 8 ms.
- The load times reflect a fast connection. On a typical connection, expect a cold download of 670 MB to take minutes. Later loads come from IndexedDB.
- ORT logs `Unknown CPU vendor` as a console error on Apple Silicon. It is harmless.

## 8. Integration notes for the portal frontend

1. **Install:** `npm i parakeet.js` (brings in `onnxruntime-web@1.24.1`). Alias `onnxruntime-web` → `onnxruntime-web/wasm` to drop the WebGPU code.
2. **Run in a Web Worker.** Session creation and `transcribe()` block the thread they run on (`proxy` is off). Import parakeet.js inside a dedicated worker and post `Float32Array` buffers to it as transferables. Decoding must stay on the main thread, because `AudioContext` is unavailable in workers.
3. **Load the model on demand.** The 670 MB first download should be an explicit user action with a progress bar (`progress` callback), not part of page load. Consider `navigator.storage.persist()` so the browser does not evict the IndexedDB cache.
4. **Memory.** To watch it live, run `top -pid <PID> -stats pid,command,mem`. MEM is the physical footprint, the number Chrome shows on tab hover; `ps` RSS undercounts it. parakeet.js has **no dispose/release API**, so loading a second model in the same tab keeps the first model's sessions alive. Load exactly one model per page lifetime.

   **Why the stock int8 build uses about 1.46 GB.** ORT Web copies the whole single-file `.onnx` (652 MB) into the WASM heap. `OrtCreateSession` then copies the initializers out of it into tensors, and finally frees the original buffer (`wasm-core-impl.ts`: `copyFromExternalBuffer` → `_OrtCreateSession` → `_free`). WASM linear memory never shrinks, so the high-water mark of about 2× the weights stays committed for the life of the tab. A forced GC does not change it.

   **Fix: external-data format.** Re-save the ONNX file with its weights in a separate `.data` file (`onnx.save_model(..., save_as_external_data=True, all_tensors_to_one_file=True, location="<name>.onnx.data")`). Pass it as `encoderDataUrl` plus `filenames: { encoder: '<name>.onnx', ... }` to `fromUrls`. ORT then keeps the data file in a JS `Uint8Array` (mounted via `externalData`), copies each tensor directly into the WASM heap, and unmounts the file. The 600 MB JS buffer is garbage-collected on its own, within about 30 s in testing.

   Measured on 2026-10-02 (Apple M5, Chrome, 8 WASM threads, JFK 11 s clip ×3, all transcripts correct):

   | Encoder build | Tab footprint (settled) | Transcribe 11 s (warm) | Encoder download |
   | --- | --- | --- | --- |
   | ysdede v3 int8, single file (current) | 1.46 GB | ~1.95 s | 652 MB |
   | ysdede v3 int8, **external data** | **0.85 GB** | ~1.87 s | 651 MB (42 MB graph + 609 MB data) |
   | same, plus `enableCpuMemArena: false` | 0.85 GB | ~1.87 s | — (no meaningful gain) |
   | Olicorne v3-ultra int8 (MatMulNBits 8-bit), external data | 0.87 GB | ~2.40 s | 648 MB |
   | Olicorne v3-ultra w4a8 (MatMulNBits 4-bit), external data | **0.62 GB** | ~2.60 s | 382 MB |

   Notes on the table:
   - The ultra builds ([`Olicorne/parakeet-tdt-0.6b-v3-ultra-onnx`](https://huggingface.co/Olicorne/parakeet-tdt-0.6b-v3-ultra-onnx)) are moondream's post-trained v3. They have the same I/O and vocab and work unmodified with parakeet.js, and need their own int8 decoder.
   - Their README reports FLEURS macro WER of 11.57% for int8 vs 12.19% for w4a8.
   - On WASM, MatMulNBits kernels are about 25–35% slower than the stock build's MatMulInteger.
   - No public repo ships the stock int8 encoder in external-data format, so the converted files must be self-hosted.
   - Lower-end and mobile devices may still fail. Feature-detect, and fall back to server STT. Lower-end and mobile devices may fail. Feature-detect, and fall back to server STT.
5. **Self-host models for production.** Use `fromUrls` against your own CDN instead of HF `resolve/main`, and pin a revision for reproducibility.
6. **Model choice (decided 2026-10-02: multilingual → v3 only).** `parakeet-tdt-0.6b-v3` was preferred for transcription quality after trying both models. v2 (English-only) is about 10% faster and has a 9 MB decoder instead of 18 MB. The encoder is the same 652 MB, so v2 would not meaningfully cut download size or memory.
7. **Licensing:** the model weights are CC-BY-4.0, which requires attribution. parakeet.js is MIT.

## 9. Moonshine v2 Medium Streaming (English only) — CHOSEN 2026-10-02

> **Decision:** Moonshine replaces Parakeet as the browser speech-to-text model because it uses less tab memory (about 0.6 GB vs 0.86 GB) at the same speed. It is English only. Sections 1–8 describe the Parakeet evaluation and are kept for reference. See `docs/decisions.md`.

Separate experiment: [`experiments/moonshine_browser_stt/moonshine_wasm_stt.html`](../experiments/moonshine_browser_stt/moonshine_wasm_stt.html), which runs Moonshine only. Setup and run commands are in its header comment, and its models live in its own gitignored `models/` folder.

**Model.** [`moonshine-ai/moonshine-streaming-medium`](https://huggingface.co/moonshine-ai/moonshine-streaming-medium):
- 245M parameters, MIT licence, **English only**.
- Built from a 50 Hz time-domain frontend, a sliding-window ("ergodic") encoder, an adapter, and an autoregressive RoPE decoder.
- Model card average Open ASR WER is 6.65%.

**Runtime support (checked 2026-10-02).** The official repo ships safetensors only, and no JS library supports this architecture yet:
- `@moonshine-ai/moonshine-js` 0.1.29 only loads v1 models.
- transformers.js 4.3.0 only has `moonshine` (v1).
- Moonshine's native runtime uses a separate `.ort` bundle from `download.moonshine.ai`: `frontend.*.ort`, `encoder.ort`, `adapter.ort`, `cross_kv.ort`, `decoder_kv.ort` and `tokenizer.bin`, about 270 MB in total. That server sends no CORS headers, and using the bundle would mean porting `core/moonshine-streaming-model.cpp` (about 1.6k lines).

The page therefore uses the community export **[`Immortalizer/moonshine-streaming-medium-onnx`](https://huggingface.co/Immortalizer/moonshine-streaming-medium-onnx)**, with a hand-written loop on raw onnxruntime-web:
- It has the same int8 weights as [`Mazino0/moonshine-streaming-medium-onnx`](https://huggingface.co/Mazino0/moonshine-streaming-medium-onnx).
- Its two split decoders are merged into one graph, so they are not both resident at once.
- Both files were re-saved in external-data format (§8.4).

| File | Size |
| --- | --- |
| `encoder_model_quantized.onnx` + `.data` | 0.9 MB + 141 MB |
| `decoder_model_merged_quantized.onnx` + `.data` | 5.7 MB + 233 MB |
| `tokenizer.json` | 3.8 MB (BPE, 32,768 vocab, byte fallback) |

**I/O and decode loop** (as implemented in the `engine` object of the Moonshine page; first validated against Python onnxruntime):
- **Encoder:** inputs are `input_values` float32 `[1, N]` (raw 16 kHz audio, no normalization, zero-padded to a multiple of 80 samples) and `attention_mask` int64 `[1, N]` (1 = real sample). The output is `encoder_hidden_states` `[1, T, 768]`, with T ≈ N/320 (50 Hz).
- **Decoder inputs:**
  - `input_ids` int64 `[1, 1]`
  - `encoder_hidden_states`
  - `use_cache_branch` bool `[1]`
  - 56 cache tensors `past_key_values.{0..13}.{decoder,encoder}.{key,value}`, each float32 `[1, 10, seq, 64]`
- **Decoder outputs:** `logits` `[1, 1, 32768]` and the matching `present.*` tensors.
- **Step 0:** feed BOS (`1`), `use_cache_branch=false`, and empty `[1, 10, 0, 64]` caches. Keep the `present.*.encoder.*` outputs (the cross-attention cache), which are reused unchanged for every later step.
- **Steps 1…n:** feed the previous token, `use_cache_branch=true`, and the `present.*.decoder.*` tensors from the previous step. Greedy argmax, stop on EOS (`2`) or after `ceil(seconds × 6.5)` tokens; the model card uses that cap against hallucination loops.
- **Detokenize:** skip ids ≤ 2 and ≥ 32000 (added `<<ST_n>>` tokens), map `▁` to a space, turn `<0xNN>` pieces into UTF-8 bytes, and strip one leading space.
- **Long audio:** split into pieces of at most 30 s at the quietest 50 ms window in the last 5 s of each piece.

**Measured** (same machine and settings as §7, 8 WASM threads):

| | Parakeet v3 int8 (external data) | Moonshine Medium int8 (external data) |
| --- | --- | --- |
| Files | ~670 MB | ~385 MB |
| Tab footprint (settled) | 0.86 GB | **0.61 GB** |
| Load (local files) | 1.4 s | 1.5 s |
| JFK 11 s | 1.9 s (encode 1.84 s) | 1.8–1.9 s (encode 1.2 s, decode 0.65 s / 26 tokens) |
| 44 s clip (JFK ×4) | — | 8.1 s, 5.4× real time, 2 segments, all four repeats correct |
| Languages | 25 European | English only |

Caveats:
- This is **batch use of a streaming model**. Each recording is encoded in one go, without the low-latency incremental encoding the architecture was designed for.
- Decode cost grows with transcript length: each step passes the 14-layer cross-attention cache (about 39 MB for 11 s of audio) between JS and WASM.
- The export is community-made with few downloads, so check accuracy on your own audio before relying on it.

## 10. Sources

- Moonshine: model card https://huggingface.co/moonshine-ai/moonshine-streaming-medium · ONNX exports https://huggingface.co/Immortalizer/moonshine-streaming-medium-onnx and https://huggingface.co/Mazino0/moonshine-streaming-medium-onnx · runtime source https://github.com/moonshine-ai/moonshine (`core/moonshine-streaming-model.cpp`, `core/moonshine-model-file-metadata.generated.cpp`) · MoonshineJS docs https://dev.moonshine.ai/js
- npm `parakeet.js@1.4.4` package source and README: https://www.npmjs.com/package/parakeet.js · repo https://github.com/ysdede/parakeet.js · API docs https://ysdede.github.io/parakeet.js/api/
- Upstream demo `examples/demo/src/App.jsx`: https://github.com/ysdede/parakeet.js/blob/master/examples/demo/src/App.jsx
- Model repos: https://huggingface.co/ysdede/parakeet-tdt-0.6b-v3-onnx · https://huggingface.co/ysdede/parakeet-tdt-0.6b-v2-onnx
- Demo Spaces: https://huggingface.co/spaces/ysdede/parakeet.js-demo · Keet: https://ysdede.github.io/keet/
- ORT Web env flags and session options: https://onnxruntime.ai/docs/tutorials/web/env-flags-and-session-options.html
- ORT Web performance diagnosis: https://onnxruntime.ai/docs/tutorials/web/performance-diagnosis.html
- Cross-origin isolation (COOP/COEP): https://web.dev/articles/coop-coep
