/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Python backend (app/api.py) runs on 127.0.0.1:8000. In development the
// browser only talks to Vite, which forwards these paths to the backend, so the
// frontend uses relative URLs and needs no CORS setup.
const BACKEND_URL = 'http://127.0.0.1:8000'
const proxy = {
  '/api': { target: BACKEND_URL },
  '/health': { target: BACKEND_URL },
}

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
})
