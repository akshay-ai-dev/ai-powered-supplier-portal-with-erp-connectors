# Decisions log

Record every "we chose X" here once, with the date (SRS §9.6). Newest first.

| Date | Decision | Why | Who |
|------|----------|-----|-----|
| 2026-09-28 | Root `package.json` scripts (npm workspaces + concurrently) instead of a Makefile; `.gitattributes` forces LF | Team uses native Windows (PowerShell) as well as macOS; `make` is not available on Windows | |
| 2026-09-28 | Backend: Python 3.12, FastAPI, uv, ruff, pytest | SRS §2.1 and §9.1 | |
| 2026-09-28 | Frontend: React 18 + TypeScript, Vite, Tailwind CSS v4, shadcn/ui | SRS §2.1 | |
| 2026-09-28 | One `.env` at the repo root, shared by backend and frontend (Vite `envDir: ".."`) | Single place for config; only `VITE_*` vars reach the browser | |
