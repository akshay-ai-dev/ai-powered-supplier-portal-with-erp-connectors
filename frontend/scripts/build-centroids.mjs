#!/usr/bin/env node
// Precomputes the semantic router's route centroids into src/lib/router/centroids.json, with the same
// model and dtype the browser uses. Re-run after editing routes.json (the worker detects a stale file
// and recomputes in the browser, which costs a second or two on first load).
//
//   npm run build:centroids     (needs `npm run fetch:models` first; the model is read from public/models)
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { env, pipeline } from "@huggingface/transformers";

const MODEL = "Xenova/all-MiniLM-L6-v2";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dir = join(root, "src", "lib", "router");
const routes = JSON.parse(readFileSync(join(dir, "routes.json"), "utf8"));

// Same hash as router.worker.ts.
function routesHash(r) {
  let h = 0x811c9dc5;
  for (const ch of JSON.stringify(r)) h = Math.imul(h ^ ch.charCodeAt(0), 0x01000193) >>> 0;
  return h.toString(16);
}

// Same as stripRequestNumbers in router.worker.ts.
const strip = (t) =>
  t.replace(/\bREQ[\s-]?#?\d+\b/gi, " ").replace(/\brequest\s+#?\d{3,}\b/gi, " ").replace(/\s+/g, " ").trim();

env.allowRemoteModels = false;
env.localModelPath = join(root, "public", "models") + "/";
const extractor = await pipeline("feature-extraction", MODEL, { dtype: "q8" });

const centroids = {};
for (const [route, utterances] of Object.entries(routes)) {
  const vecs = (await extractor(utterances.map(strip), { pooling: "mean", normalize: true })).tolist();
  const mean = vecs[0].map((_, i) => vecs.reduce((s, v) => s + v[i], 0) / vecs.length);
  const norm = Math.hypot(...mean) || 1;
  centroids[route] = mean.map((x) => +(x / norm).toFixed(6));
  console.log(`${route}: ${utterances.length} utterances`);
}

writeFileSync(join(dir, "centroids.json"), JSON.stringify({ model: MODEL, dtype: "q8", routesHash: routesHash(routes), centroids }) + "\n");
console.log("Wrote src/lib/router/centroids.json");
