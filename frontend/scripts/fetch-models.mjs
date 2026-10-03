#!/usr/bin/env node
// Puts the AI Assistant's browser models under public/models/ (gitignored), so the browser loads
// everything from the portal itself and never from Hugging Face or a CDN.
//
//   node scripts/fetch-models.mjs            models + ONNX Runtime files (run once after install)
//   node scripts/fetch-models.mjs --ort-only only the ONNX Runtime files (runs before `next build`)
//
// public/models/
//   Xenova/all-MiniLM-L6-v2/          semantic router (~23 MB), Transformers.js local-model layout
//   moonshine-streaming-medium/       voice input (~385 MB), external-data ONNX
//   ort/transformers/  ort/moonshine/ ONNX Runtime WASM, one folder per ORT version
//
// Moonshine is copied from experiments/moonshine_browser_stt/models/ when present; otherwise it is
// downloaded once and re-saved in external-data format, which needs `uv` (Python onnx).
import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "models");
const HF = "https://huggingface.co";

const MINILM = { repo: "Xenova/all-MiniLM-L6-v2", files: ["config.json", "tokenizer.json", "tokenizer_config.json", "onnx/model_quantized.onnx"] };
const MOONSHINE = {
  repo: "Immortalizer/moonshine-streaming-medium-onnx",
  graphs: ["encoder_model_quantized.onnx", "decoder_model_merged_quantized.onnx"],
  experiment: join(root, "..", "experiments", "moonshine_browser_stt", "models", "moonshine-streaming-medium"),
  dir: join(out, "moonshine-streaming-medium"),
};

async function download(url, dest) {
  if (existsSync(dest)) return console.log(`  have ${dest.slice(out.length + 1)}`);
  mkdirSync(dirname(dest), { recursive: true });
  console.log(`  get  ${url}`);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  writeFileSync(dest, Buffer.from(await res.arrayBuffer()));
}

function copy(src, dest, overwrite = false) {
  if (existsSync(dest) && !overwrite) return;
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(src, dest);
}

async function fetchMiniLM() {
  console.log(`Router model: ${MINILM.repo}`);
  for (const f of MINILM.files) await download(`${HF}/${MINILM.repo}/resolve/main/${f}`, join(out, MINILM.repo, f));
}

async function fetchMoonshine() {
  console.log("Voice model: moonshine-streaming-medium");
  const files = [...MOONSHINE.graphs.flatMap((g) => [g, `${g}.data`]), "tokenizer.json"];
  if (files.every((f) => existsSync(join(MOONSHINE.experiment, f)))) {
    console.log("  copying from experiments/moonshine_browser_stt/models/");
    for (const f of files) copy(join(MOONSHINE.experiment, f), join(MOONSHINE.dir, f));
    return;
  }
  for (const f of [...MOONSHINE.graphs, "tokenizer.json"]) await download(`${HF}/${MOONSHINE.repo}/resolve/main/${f}`, join(MOONSHINE.dir, f));
  if (MOONSHINE.graphs.every((g) => existsSync(join(MOONSHINE.dir, `${g}.data`)))) return;
  console.log("  re-saving graphs with external data (uv + onnx)");
  const py =
    "import onnx; [onnx.save_model(onnx.load(n), n, save_as_external_data=True, all_tensors_to_one_file=True, location=n+'.data', size_threshold=1024) " +
    `for n in (${MOONSHINE.graphs.map((g) => `'${g}'`).join(", ")})]`;
  execFileSync("uv", ["run", "--with", "onnx", "python", "-c", py], { cwd: MOONSHINE.dir, stdio: "inherit" });
}

// Copies ORT's WASM build from node_modules. Transformers.js bundles its own ORT version, so each
// worker gets the runtime files matching the ORT JS it was built with.
function copyOrt() {
  const req = createRequire(join(root, "package.json"));
  const pkgDir = (entry) => {
    let dir = dirname(entry);
    while (!dir.endsWith("onnxruntime-web")) {
      if (dir === dirname(dir)) throw new Error(`onnxruntime-web not found above ${entry}`);
      dir = dirname(dir);
    }
    return dir;
  };
  let transformersEntry;
  try {
    transformersEntry = req.resolve("@huggingface/transformers");
  } catch {
    console.warn("ORT files skipped: run `npm install` in frontend/ first.");
    return;
  }
  const targets = [
    { from: pkgDir(createRequire(transformersEntry).resolve("onnxruntime-web")), to: "transformers", variant: ".asyncify" },
    { from: pkgDir(req.resolve("onnxruntime-web")), to: "moonshine", variant: "" },
  ];
  for (const { from, to, variant } of targets) {
    for (const ext of ["mjs", "wasm"]) {
      const name = `ort-wasm-simd-threaded${variant}.${ext}`;
      copy(join(from, "dist", name), join(out, "ort", to, name), true);
    }
  }
  console.log("ONNX Runtime files: public/models/ort/");
}

const ortOnly = process.argv.includes("--ort-only");
if (!ortOnly) {
  await fetchMiniLM();
  await fetchMoonshine();
}
copyOrt();
