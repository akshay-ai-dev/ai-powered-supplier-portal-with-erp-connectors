# Decisions log

Record every "we chose X" here once, with the date (SRS §9.6). Newest first.

| Date | Decision | Why | Who |
|------|----------|-----|-----|
| 2026-10-02 | AI Assistant answers use **fixed templates**, one layout per tool, filled only from the tool result. No LLM writes the answers | A buyer uses this tool many times a day for the same few jobs: checking status, comparing responses, finding a PO, seeing why something was rejected. Here consistency is the feature. When the same question gets the same answer layout every time, people learn where to look, scan it in two seconds, and trust it. If the answer varied in wording or format, it would read as unreliable, which is the opposite of what someone approving a purchase order wants. | Akshay |
| 2026-10-02 | AI Assistant picks the tool with a **client-side semantic router**: all-MiniLM-L6-v2 (q8, Transformers.js, WASM, Web Worker) scored against precomputed route centroids (TAU 0.40, DELTA 0.05, "none" otherwise). Browser models are served from `frontend/public/models/` (gitignored), never from Hugging Face or a CDN | Runs in the browser with no LLM or server inference; 23 MB model, cached after the first load. Models move to file storage later by changing `NEXT_PUBLIC_MODELS_URL` | Akshay |
| 2026-10-02 | Browser speech-to-text: Moonshine v2 Medium Streaming (English, int8 ONNX, `Immortalizer/moonshine-streaming-medium-onnx`) on ONNX Runtime Web WASM, weights in external-data format. Chosen over NVIDIA Parakeet TDT 0.6B v3 | Lower tab memory (~0.6 GB vs ~0.86 GB) at the same speed (~6× real time on 8 threads); smaller download (~385 MB vs ~670 MB). Trade-off: English only. See `docs/STT_API_REFERENCE.md` §9 and `experiments/moonshine_browser_stt/` | Akshay |
| 2026-09-28 | Root `package.json` scripts (npm workspaces + concurrently) instead of a Makefile; `.gitattributes` forces LF | Team uses native Windows (PowerShell) as well as macOS; `make` is not available on Windows | |
| 2026-09-28 | Backend: Python 3.12, FastAPI, uv, ruff, pytest | SRS §2.1 and §9.1 | |
| 2026-09-28 | Frontend: React 18 + TypeScript, Vite, Tailwind CSS v4, shadcn/ui | SRS §2.1 | |
| 2026-09-28 | One `.env` at the repo root, shared by backend and frontend (Vite `envDir: ".."`) | Single place for config; only `VITE_*` vars reach the browser | |
